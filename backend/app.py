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

import json
import os
import re
import secrets
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import github_backup
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
}

_tokens: dict[str, float] = {}  # token -> expiry ts


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
        for key in ("teachers", "subjects", "bell_schedule", "second_shift_classes", "updated_at"):
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
def _check_token(token: str) -> bool:
    expiry = _tokens.get(token, 0)
    if time.time() < expiry:
        return True
    _tokens.pop(token, None)
    return False


def require_admin(authorization: str = Header(default="")) -> None:
    token = authorization.removeprefix("Bearer ").strip()
    if not token or not _check_token(token):
        raise HTTPException(status_code=401, detail="Требуется вход администратора")


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
    state[kind] = data
    state["files"][kind] = source_name
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


# --------------------------------------------------------------------- админ API
@app.post("/api/admin/login")
def login(body: LoginBody) -> dict:
    if body.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="Неверный пароль")
    token = secrets.token_hex(24)
    _tokens[token] = time.time() + TOKEN_TTL
    return {"token": token}


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
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/admin", include_in_schema=False)
def admin_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "admin.html")


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
