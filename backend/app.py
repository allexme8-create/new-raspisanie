"""
Backend «Расписание лицея».

Публичная часть:
  GET /api/schedule -> сетки расписания, время звонков и дата обновления

Администратор (Authorization: Bearer <token>):
  POST   /api/admin/login
  GET    /api/admin/status
  POST   /api/admin/upload          -> файлы учителей/предметов
  POST   /api/admin/bell-schedule   -> отдельный файл расписания звонков
  PUT    /api/admin/settings        -> классы второй смены
  POST   /api/admin/fetch-yandex
  DELETE /api/admin/file/{kind}
"""
from __future__ import annotations

import csv
import io
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import threading
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests
from fastapi import Cookie, Depends, FastAPI, File, Header, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import github_backup
import planner
import staff
from schedule_parser import (
    ParseError,
    parse_bell_schedule_file,
    parse_schedule_file,
)

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = (BASE_DIR.parent / "frontend").resolve()
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
STATE_FILE = DATA_DIR / "state.json"

DATA_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
ADMIN_TOKEN_SECRET = (os.environ.get("ADMIN_TOKEN_SECRET") or ADMIN_PASSWORD).encode("utf-8")
TOKEN_TTL = 12 * 60 * 60  # 12 часов

app = FastAPI(title="Расписание лицея", docs_url="/api/docs")

# Схема совместима с прежним state.json: новые поля имеют безопасные значения.
state: dict = {
    "teachers": None,
    "subjects": None,
    "files": {"teachers": None, "subjects": None},
    "bell_schedule": None,
    "second_shift_classes": [],
    "updated_at": None,
    "planner": None,
    "planner_class_imported": False,
}

_revoked_tokens: set[str] = set()


def _save_state() -> None:
    content = json.dumps(state, ensure_ascii=False)
    STATE_FILE.write_text(content, encoding="utf-8")
    # Асинхронный бэкап в GitHub (если настроен).
    github_backup.schedule_backup(content)


def _load_state() -> None:
    if not STATE_FILE.exists():
        return
    try:
        saved = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        for key in ("teachers", "subjects", "bell_schedule", "second_shift_classes", "updated_at", "planner", "planner_class_imported"):
            if key in saved:
                state[key] = saved[key]
        if isinstance(saved.get("files"), dict):
            state["files"].update(saved["files"])
        if not isinstance(state.get("second_shift_classes"), list):
            state["second_shift_classes"] = []
    except Exception:  # noqa: BLE001 - не блокируем запуск при повреждённом state
        pass


def _restore_state_if_needed() -> None:
    """На эфемерных хостингах восстанавливаем состояние из GitHub при старте."""
    if STATE_FILE.exists() or not github_backup.enabled():
        return
    blob = github_backup.restore_state()
    if blob:
        STATE_FILE.write_bytes(blob)
        _load_state()


_load_state()
_restore_state_if_needed()


# ------------------------------------------------------------------ авторизация
def _create_token() -> str:
    """Подписанный токен не зависит от памяти отдельного worker-процесса."""
    expiry = str(int(time.time() + TOKEN_TTL))
    payload = f"{expiry}.{secrets.token_hex(16)}"
    signature = hmac.new(ADMIN_TOKEN_SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _check_token(token: str) -> bool:
    if not token or token in _revoked_tokens:
        return False
    try:
        expiry, nonce, signature = token.split(".", 2)
        if not expiry.isdecimal() or not nonce or len(signature) != 64:
            return False
        payload = f"{expiry}.{nonce}"
        expected = hmac.new(ADMIN_TOKEN_SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return time.time() < int(expiry) and hmac.compare_digest(signature, expected)
    except (ValueError, OverflowError):
        return False


def require_admin(
    authorization: str = Header(default=""),
    x_admin_token: str = Header(default="", alias="X-Admin-Token"),
    schedule_admin_token: str = Cookie(default=""),
) -> None:
    # Веб-клиент использует Bearer-заголовок; cookie — запасной вариант для
    # reverse proxy, которые могут удалять Authorization из браузерных запросов.
    tokens = (
        authorization.removeprefix("Bearer ").strip(),
        x_admin_token.strip(),
        schedule_admin_token,
    )
    if not any(_check_token(token) for token in tokens if token):
        raise HTTPException(status_code=401, detail="Требуется вход администратора")


def require_admin_header(
    authorization: str = Header(default=""),
    x_admin_token: str = Header(default="", alias="X-Admin-Token"),
) -> None:
    # Для работы с паролями cookie недостаточно: обязательный проверенный заголовок защищает от CSRF.
    tokens = (authorization.removeprefix("Bearer ").strip(), x_admin_token.strip())
    if not any(_check_token(token) for token in tokens if token):
        raise HTTPException(status_code=401, detail="Требуется вход администратора")


# Единая блокировка черновика и привязок классов для одного процесса.
_planner_lock = threading.Lock()
# Персональные данные не включаются в GitHub-бэкап публичного расписания.
staff_store = staff.Store(DATA_DIR / "staff.sqlite3")
app.include_router(staff.make_router(staff_store, require_admin_header,
    class_catalog=lambda: [c.name for c in _planner_project().classes], catalog_lock=_planner_lock))


@app.middleware("http")
async def private_no_cache(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/api/staff/", "/api/admin/users", "/api/duties/")) or request.url.path == "/users":
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
    return response


class LoginBody(BaseModel):
    password: str


class YandexBody(BaseModel):
    url: str


class AdminSettingsBody(BaseModel):
    second_shift_classes: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------ состояние
def _available_classes() -> list[str]:
    """Классы из загруженных сеток (сохраняем порядок первого файла)."""
    result: list[str] = []
    seen: set[str] = set()
    for kind in ("teachers", "subjects"):
        data = state.get(kind) or {}
        for name in data.get("classes", []):
            value = str(name).strip()
            if value and value not in seen:
                result.append(value)
                seen.add(value)
    return result


def _second_shift_classes() -> list[str]:
    available = set(_available_classes())
    return [
        name for name in state.get("second_shift_classes", [])
        if name in available
    ]


def _touch_updated_at() -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat()


def _safe_upload_name(source_name: str) -> str:
    return re.sub(r"[^0-9A-Za-zА-Яа-яЁё._-]+", "_", source_name)[:80] or "upload"


def _ingest(buf: bytes, source_name: str) -> str:
    """Разобрать сетку расписания, сохранить её в state и на диск."""
    try:
        kind, data = parse_schedule_file(buf, source_name)
    except (ParseError, KeyError) as exc:
        raise ParseError(str(exc)) from exc
    safe = _safe_upload_name(source_name)
    (UPLOAD_DIR / f"{kind}__{safe}").write_bytes(buf)
    with _planner_lock:
        previous_data,previous_name=state[kind],state["files"][kind]
        state[kind] = data
        state["files"][kind] = source_name
        try:
            _import_schedule_classes()
        except ValueError as exc:
            state[kind],state["files"][kind]=previous_data,previous_name
            raise ParseError(str(exc)) from exc
        state["planner_class_imported"] = True
        _touch_updated_at()
        _save_state()
    return kind


def _stats_of(kind: str) -> dict | None:
    data = state.get(kind)
    if not data:
        return None
    lessons = sum(len(day) for day in data.get("grid", {}).values())
    return {
        "kind": kind,
        "filename": state["files"].get(kind),
        "classes": len(data.get("classes", [])),
        "days_with_lessons": sum(1 for day in data.get("grid", {}).values() if day),
        "lesson_rows": lessons,
    }


def _bell_stats() -> dict | None:
    bell = state.get("bell_schedule")
    if not bell:
        return None
    shifts = bell.get("shifts", {})
    return {
        "filename": bell.get("filename"),
        "lesson_rows": sum(
            len(lessons)
            for days in shifts.values()
            for lessons in days.values()
        ),
        "shifts": [shift for shift in ("1", "2") if shifts.get(shift)],
    }


# ------------------------------------------------------------------ публичное API
@app.get("/api/schedule")
def get_schedule() -> JSONResponse:
    bell = state.get("bell_schedule")
    return JSONResponse(
        {
            "teachers": state["teachers"],
            "subjects": state["subjects"],
            "bell_schedule": {"shifts": bell["shifts"]} if bell else None,
            "second_shift_classes": _second_shift_classes(),
            "updated_at": state["updated_at"],
        }
    )


@app.get("/api/status")
def get_status() -> dict:
    return {
        "ready": bool(state["teachers"] or state["subjects"]),
        "updated_at": state["updated_at"],
    }


# Черновик хранится отдельно от опубликованного расписания.


def _planner_project() -> planner.Project:
    return planner.Project.model_validate(state.get("planner") or {})


def _import_schedule_classes() -> list[str]:
    """Merge published schedule classes into the draft without replacing its data.

    Caller holds _planner_lock and saves the state. Existing names and shifts win.
    """
    project = _planner_project()
    names = {c.name.casefold() for c in project.classes}
    added = []
    second_shift = set(_second_shift_classes())
    for name in _available_classes():
        if name.casefold() in names:
            continue
        if len(project.classes)>=500 or len(name)>80:
            raise ValueError("Невозможно перенести все классы: превышен предел конструктора или длина названия")
        project.classes.append(planner.SchoolClass(name=name,shift=2 if name in second_shift else 1))
        names.add(name.casefold()); added.append(name)
    if added:
        project.revision += 1
        state["planner"] = project.model_dump()
    return added


@app.on_event("startup")
def migrate_schedule_classes():
    # One-time migration; do not resurrect a class deliberately deleted later.
    with _planner_lock:
        if not state.get("planner_class_imported") and _available_classes():
            _import_schedule_classes()
            state["planner_class_imported"] = True
            _save_state()


@app.post("/api/admin/planner/import-classes")
def import_schedule_classes(_: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        try:
            added=_import_schedule_classes()
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from exc
        if added:
            _save_state()
        return {"added":added,"project":_planner_project().model_dump()}


@app.get("/api/admin/planner")
def planner_get(_: None = Depends(require_admin)) -> dict:
    project = _planner_project()
    return {"project": project.model_dump(), "issues": planner.issues(project, state.get("bell_schedule"), complete=True)}


@app.put("/api/admin/planner")
def planner_save(project: planner.Project, _: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        if project.revision != _planner_project().revision:
            raise HTTPException(status_code=409, detail="Черновик изменён в другом окне. Обновите конструктор перед сохранением.")
        errors = planner.references(project)
        if errors:
            raise HTTPException(status_code=422, detail=" ".join(errors[:5]))
        class_names={c.name for c in project.classes}
        with staff_store.connect() as db:
            assigned={row[0] for row in db.execute("SELECT DISTINCT homeroom_class FROM users WHERE active=1 AND role='teacher' AND homeroom_class<>''")}
        missing=sorted(assigned-class_names)
        if missing:
            raise HTTPException(status_code=409, detail="Нельзя удалить класс с классным руководителем: "+", ".join(missing)+". Сначала измените привязку в списке пользователей.")
        project.revision += 1
        state["planner"] = project.model_dump()
        _save_state()
        return {"project": project.model_dump(), "issues": planner.issues(project, state.get("bell_schedule"), complete=True)}


class PlannerAction(BaseModel):
    revision: int = Field(ge=0)


@app.post("/api/admin/planner/generate")
def planner_generate(body: PlannerAction, _: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        project = _planner_project()
        if body.revision != project.revision:
            raise HTTPException(status_code=409, detail="Черновик изменён в другом окне. Обновите конструктор.")
        generated, error = planner.generate(project, state.get("bell_schedule"))
        if generated is None:
            raise HTTPException(status_code=422, detail=error)
        generated.revision += 1
        state["planner"] = generated.model_dump()
        _save_state()
        return {"project": generated.model_dump(), "issues": planner.issues(generated, state.get("bell_schedule"), complete=True)}


@app.post("/api/admin/planner/publish")
def planner_publish(body: PlannerAction, _: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        project = _planner_project()
        if body.revision != project.revision:
            raise HTTPException(status_code=409, detail="Черновик изменён в другом окне. Обновите конструктор.")
        errors = planner.issues(project, state.get("bell_schedule"), complete=True)
        if not project.loads:
            errors.append("Добавьте учебную нагрузку.")
        if errors:
            raise HTTPException(status_code=422, detail=" ".join(errors[:5]))
        state["teachers"], state["subjects"] = planner.public_grids(project)
        state["second_shift_classes"] = [c.name for c in project.classes if c.shift == 2]
        state["files"]["teachers"] = state["files"]["subjects"] = "Конструктор расписания"
        _touch_updated_at()
        _save_state()
        return {"updated_at": state["updated_at"]}


# --------------------------------------------------------------------- админ API
@app.post("/api/admin/login")
def login(body: LoginBody, response: Response) -> dict:
    if body.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="Неверный пароль")
    token = _create_token()
    response.set_cookie(
        key="schedule_admin_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=TOKEN_TTL,
        path="/",
    )
    return {"token": token}


@app.post("/api/admin/logout")
def admin_logout(
    response: Response,
    authorization: str = Header(default=""),
    x_admin_token: str = Header(default="", alias="X-Admin-Token"),
    schedule_admin_token: str = Cookie(default=""),
) -> dict:
    token = (
        authorization.removeprefix("Bearer ").strip()
        or x_admin_token.strip()
        or schedule_admin_token
    )
    if token:
        _revoked_tokens.add(token)
    response.delete_cookie(key="schedule_admin_token", path="/")
    return {"ok": True}


@app.get("/api/admin/status")
def admin_status(_: None = Depends(require_admin)) -> dict:
    return {
        "teachers": _stats_of("teachers"),
        "subjects": _stats_of("subjects"),
        "bell_schedule": _bell_stats(),
        "classes": _available_classes(),
        "second_shift_classes": _second_shift_classes(),
        "updated_at": state["updated_at"],
        "backup": github_backup.backup_status(),
    }


@app.post("/api/admin/upload")
async def admin_upload(
    _: None = Depends(require_admin),
    files: list[UploadFile] = File(...),
) -> dict:
    results = []
    for upload in files:
        buf = await upload.read()
        name = upload.filename or "file"
        try:
            kind = _ingest(buf, name)
        except ParseError as exc:
            results.append({"file": name, "ok": False, "error": str(exc)})
            continue
        results.append(
            {
                "file": name,
                "ok": True,
                "kind": kind,
                "classes": len(state[kind]["classes"]),
            }
        )
    return {"results": results, "updated_at": state["updated_at"]}


@app.get("/api/admin/bell-schedule.csv")
def admin_download_bell_schedule(_: None = Depends(require_admin)) -> Response:
    """Экспорт текущих данных звонков в CSV, совместимый с импортом."""
    bell = state.get("bell_schedule")
    if not bell or not bell.get("shifts"):
        raise HTTPException(404, "Расписание звонков не загружено")
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";", lineterminator="\r\n")
    writer.writerow(["1 смена", "", "", "", "2 смена", "", "", ""])
    writer.writerow(["День недели", "Урок", "Начало", "Окончание"] * 2)
    days = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
    blocks = []
    for shift in ("1", "2"):
        entries = []
        for day in days:
            lessons = bell["shifts"].get(shift, {}).get(day, {})
            for lesson, period in sorted(lessons.items(), key=lambda item: int(item[0])):
                entries.append([day, lesson, period["start"], period["end"]])
        blocks.append(entries)
    for index in range(max(map(len, blocks))):
        writer.writerow(sum((block[index] if index < len(block) else ["", "", "", ""] for block in blocks), []))
    return Response(content=output.getvalue().encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="bell-schedule.csv"', "Cache-Control": "no-store"})


@app.post("/api/admin/bell-schedule")
async def admin_upload_bell_schedule(
    _: None = Depends(require_admin),
    file: UploadFile = File(...),
) -> dict:
    """Отдельно загрузить расписание звонков для первой и второй смен."""
    name = file.filename or "bell-schedule.csv"
    buf = await file.read()
    try:
        parsed = parse_bell_schedule_file(buf, name)
    except ParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    safe = _safe_upload_name(name)
    (UPLOAD_DIR / f"bell__{safe}").write_bytes(buf)
    state["bell_schedule"] = {"filename": name, **parsed}
    _touch_updated_at()
    _save_state()
    return {
        "ok": True,
        "file": name,
        "lesson_rows": _bell_stats()["lesson_rows"],
        "shifts": _bell_stats()["shifts"],
        "updated_at": state["updated_at"],
    }


@app.put("/api/admin/settings")
def admin_update_settings(
    body: AdminSettingsBody,
    _: None = Depends(require_admin),
) -> dict:
    available = _available_classes()
    requested = {str(name).strip() for name in body.second_shift_classes if str(name).strip()}
    unknown = requested.difference(available)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Неизвестные классы: {', '.join(sorted(unknown))}",
        )
    state["second_shift_classes"] = [name for name in available if name in requested]
    _touch_updated_at()
    _save_state()
    return {
        "second_shift_classes": state["second_shift_classes"],
        "updated_at": state["updated_at"],
    }


@app.post("/api/admin/fetch-yandex")
def admin_fetch_yandex(body: YandexBody, _: None = Depends(require_admin)) -> dict:
    """Скачать файл расписания по публичной ссылке Яндекс.Диска."""
    public_url = body.url.strip()
    if not public_url:
        raise HTTPException(status_code=400, detail="Пустая ссылка")
    api_url = (
        "https://cloud-api.yandex.net/v1/disk/public/resources/download"
        f"?public_key={urllib.parse.quote(public_url, safe='')}"
    )
    try:
        resp = requests.get(api_url, timeout=30)
        resp.raise_for_status()
        href = resp.json().get("href")
        if not href:
            raise ValueError("Яндекс не вернул ссылку на скачивание")
        file_resp = requests.get(href, timeout=120)
        file_resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"Не удалось скачать файл с Яндекс.Диска: {exc}",
        ) from exc
    name = urllib.parse.unquote(
        urllib.parse.urlparse(href).path.rsplit("/", 1)[-1] or "yadisk_file.xls"
    )
    try:
        kind = _ingest(file_resp.content, name)
    except ParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "file": name, "kind": kind, "updated_at": state["updated_at"]}


@app.delete("/api/admin/file/{kind}")
def admin_delete(kind: str, _: None = Depends(require_admin)) -> dict:
    if kind in ("teachers", "subjects"):
        state[kind] = None
        state["files"][kind] = None
        state["second_shift_classes"] = _second_shift_classes()
    elif kind == "bell_schedule":
        state["bell_schedule"] = None
    else:
        raise HTTPException(status_code=404, detail="Неизвестный тип файла")
    _touch_updated_at()
    _save_state()
    return {"ok": True, "updated_at": state["updated_at"]}


# ----------------------------------------------------------------- статика/страницы
@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(
        FRONTEND_DIR / "index.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/admin", include_in_schema=False)
def admin_page() -> FileResponse:
    return FileResponse(
        FRONTEND_DIR / "admin.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/users", include_in_schema=False)
def users_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "staff.html", headers={"Cache-Control": "no-store"})


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict:
    return {"ok": True}


app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="css")
app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="js")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        reload=False,
    )
