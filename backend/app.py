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
import copy
from collections import Counter
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
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

import requests
from fastapi import Cookie, Depends, FastAPI, File, Header, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import github_backup
import planner
import load_import
import catalog_file
import schedule_map
import schedule_load_import
import departments
from departments import Department
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
    "planner_teachers_imported": False,
    "planner_initials_normalized": False,
    "planner_subjects_imported": False,
    "planner_rooms_imported": False,
    "planner_groups_imported": False,
    "planner_unassigned_vacancy_migrated": False,
    "schedule_map_draft": None,
    "weekly_move_notices": [],
    "dated_schedule_changes": [],
    "dated_schedule_revision": 0,
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
        for key in ("teachers", "subjects", "bell_schedule", "second_shift_classes", "updated_at", "planner", "planner_class_imported", "planner_teachers_imported", "planner_initials_normalized", "planner_subjects_imported", "planner_rooms_imported", "planner_groups_imported", "planner_unassigned_vacancy_migrated", "schedule_map_draft", "weekly_move_notices", "dated_schedule_changes", "dated_schedule_revision"):
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
_bell_lock = threading.RLock()
# Персональные данные не включаются в GitHub-бэкап публичного расписания.
staff_store = staff.Store(DATA_DIR / "staff.sqlite3")
app.include_router(staff.make_router(staff_store, require_admin_header,
    class_catalog=lambda: [c.name for c in _planner_project().classes], catalog_lock=_planner_lock))


@app.middleware("http")
async def private_no_cache(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/api/staff/", "/api/admin/", "/api/duties/")) or request.url.path == "/users":
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
    return response


class LoginBody(BaseModel):
    password: str


class YandexBody(BaseModel):
    url: str


class AdminSettingsBody(BaseModel):
    second_shift_classes: list[str] = Field(default_factory=list)


class BellEntry(BaseModel):
    shift: Literal[1, 2]
    day: Literal["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    lesson: int = Field(ge=1, le=99)
    start: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class BellEdit(BaseModel):
    revision: str
    entries: list[BellEntry] = Field(min_length=1, max_length=1386)


def bell_revision() -> str:
    data = json.dumps(state.get("bell_schedule"), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


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
            "dated_changes": public_dated_changes(),
            "weekly_moves": active_weekly_moves(),
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


def normalize_teacher_initials(name: str) -> str:
    name = " ".join(name.split())
    match = re.fullmatch(r"(.+?)\s+([А-ЯЁA-Z](?:\.?\s*[А-ЯЁA-Z]){0,2}\.?)", name)
    if not match:
        return name
    letters = re.findall(r"[А-ЯЁA-Z]", match.group(2))
    return match.group(1) + " " + "".join(letter + "." for letter in letters)


def normalize_project_teachers(project: planner.Project) -> None:
    changes = {teacher.name: normalize_teacher_initials(teacher.name) for teacher in project.teachers}
    if len({name.casefold() for name in changes.values()}) != len(changes):
        raise ValueError("Учителя совпадают после добавления точек к инициалам. Исправьте повторяющиеся имена.")
    for teacher in project.teachers:
        teacher.name = changes[teacher.name]
    for load in project.loads:
        load.teacher = changes.get(load.teacher, normalize_teacher_initials(load.teacher))


@app.on_event("startup")
def migrate_teacher_initials():
    with _planner_lock:
        if state.get("planner_initials_normalized"):
            return
        project = _planner_project()
        before = project.model_dump()
        try:
            normalize_project_teachers(project)
        except ValueError:
            return
        if project.model_dump() != before:
            project.revision += 1
            state["planner"] = project.model_dump()
        state["planner_initials_normalized"] = True
        _save_state()


def _import_schedule_teachers() -> list[str]:
    """Добавить имена из опубликованной сетки в справочник, не меняя учётные записи."""
    source = state.get("teachers") or {}
    names = set()
    for lessons in source.get("grid", {}).values():
        for cells in lessons.values():
            for cell in cells.values():
                for raw in cell.get("names", []):
                    name = str(raw).strip()
                    if not name or name in {"Классный час", "СФУ", "Экскурсия"}:
                        continue
                    if source.get("numbering") != "local" and not re.fullmatch(r"[А-ЯЁ][а-яё-]+(?:\s+(?:[А-ЯЁ]\.?){1,3})?", name):
                        continue
                    names.add(normalize_teacher_initials(name))
    project = _planner_project()
    existing = {normalize_teacher_initials(teacher.name).casefold() for teacher in project.teachers}
    added = []
    for name in sorted(names, key=str.casefold):
        if name.casefold() in existing:
            continue
        if len(project.teachers) >= 200 or len(name) > 80:
            raise ValueError("Невозможно перенести всех учителей: превышен предел конструктора или длина имени")
        project.teachers.append(planner.Teacher(name=name,departments=_vacancy_membership(project)))
        existing.add(name.casefold()); added.append(name)
    if added:
        project.revision += 1
        state["planner"] = project.model_dump()
    return added


@app.on_event("startup")
def migrate_schedule_teachers():
    with _planner_lock:
        source=state.get("teachers") or {}
        if not state.get("planner_teachers_imported") and any(source.get("grid", {}).values()):
            try:
                _import_schedule_teachers()
            except ValueError:
                return  # Explicit import reports limits; startup must remain available.
            state["planner_teachers_imported"] = True
            _save_state()


@app.post("/api/admin/planner/import-teachers")
def import_schedule_teachers(_: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        try:
            added = _import_schedule_teachers()
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if added:
            _save_state()
        return {"added": added, "project": _planner_project().model_dump()}


def _import_schedule_catalog(kind: str) -> list[str]:
    if kind not in ("subjects", "rooms"):
        raise ValueError("Неизвестный справочник")
    names = {}
    sources = ("subjects",) if kind == "subjects" else ("subjects", "teachers")
    for source in sources:
        for lessons in (state.get(source) or {}).get("grid", {}).values():
            for cells in lessons.values():
                for cell in cells.values():
                    for value in cell.get("names" if kind == "subjects" else "rooms", []):
                        name = " ".join(str(value).split())
                        if not name or (kind == "subjects" and name.casefold() in {"классный час", "сфу", "экскурсия"}):
                            continue
                        names.setdefault(name.casefold(), name)
    project = _planner_project()
    catalog = getattr(project, kind)
    existing = {" ".join(item.name.split()).casefold() for item in catalog}
    added = []
    for key in sorted(names):
        name = names[key]
        if key in existing:
            continue
        if len(catalog) >= 200 or len(name) > 80:
            raise ValueError("Невозможно перенести весь справочник: превышен предел конструктора или длина названия")
        catalog.append(planner.Room(name=name) if kind == "rooms" else planner.Named(name=name))
        existing.add(key); added.append(name)
    if added:
        project.revision += 1
        state["planner"] = project.model_dump()
    return added


@app.on_event("startup")
def migrate_schedule_catalogs():
    with _planner_lock:
        for kind, sources in (("subjects", ("subjects",)), ("rooms", ("subjects", "teachers"))):
            flag = f"planner_{kind}_imported"
            if state.get(flag) or not any(any((state.get(source) or {}).get("grid", {}).values()) for source in sources):
                continue
            try:
                _import_schedule_catalog(kind)
            except ValueError:
                continue
            state[flag] = True
            _save_state()


@app.post("/api/admin/planner/import-catalog/{kind}")
def import_schedule_catalog(kind: str, _: None = Depends(require_admin)) -> dict:
    if kind not in ("subjects", "rooms"):
        raise HTTPException(404, "Неизвестный справочник")
    with _planner_lock:
        try:
            added = _import_schedule_catalog(kind)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if added:
            _save_state()
        return {"added": added, "project": _planner_project().model_dump()}


def _import_schedule_groups() -> list[dict]:
    """Названия из метаданных или предположительные номера по разделённым ячейкам."""
    project = _planner_project()
    classes = {c.name.casefold(): c.name for c in project.classes}
    candidates = {}
    def add(cls, name, inferred):
        cls = classes.get(str(cls).strip().casefold())
        name = " ".join(str(name).split())
        if cls and name:
            key = (cls.casefold(), name.casefold())
            if key not in candidates or not inferred:
                candidates[key] = {"class_name":cls,"name":name,"inferred":inferred}
    for load in project.loads:
        if load.group:
            add(load.class_name, load.group, False)
    sources=[state.get("teachers") or {},state.get("subjects") or {}]
    for source in sources:
        for lessons in source.get("grid", {}).values():
            for cells in lessons.values():
                for cls,cell in cells.items():
                    groups=cell.get("groups") or []
                    for item in groups:
                        if item.get("group"):
                            add(cls,item["group"],False)
                    # Старые таблицы не содержат названий групп: несколько имён
                    # могут означать как деление, так и совместное преподавание.
                    if not groups:
                        count=len([x for x in cell.get("names",[]) if str(x).strip()])
                        if count>1:
                            for index in range(1,count+1): add(cls,f"{index} группа",True)
    existing={(g.class_name.casefold(),g.name.casefold()) for g in project.groups}
    added=[]
    for key, data in sorted(candidates.items()):
        if key in existing: continue
        if len(project.groups)>=2000 or len(data["name"])>80:
            raise ValueError("Невозможно перенести группы: превышен предел конструктора или длина названия")
        project.groups.append(planner.ClassGroup(**data));existing.add(key);added.append(data)
    if added:
        project.revision+=1;state["planner"]=project.model_dump()
    return added


@app.post("/api/admin/planner/import-groups")
def import_schedule_groups(_: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        try: added=_import_schedule_groups()
        except ValueError as exc: raise HTTPException(422,str(exc)) from exc
        if added: _save_state()
        return {"added":added,"project":_planner_project().model_dump()}


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


@app.on_event("startup")
def migrate_schedule_groups():
    with _planner_lock:
        if state.get("planner_groups_imported"):
            return
        if not state.get("planner") and not state.get("teachers") and not state.get("subjects"):
            return
        try:
            _import_schedule_groups()
        except ValueError:
            return
        state["planner_groups_imported"]=True
        _save_state()


def _vacancy_membership(project: planner.Project) -> list[str]:
    return [project.vacancy_department] if project.vacancy_department and any(d.name==project.vacancy_department for d in project.departments) else []


@app.on_event("startup")
def migrate_unassigned_to_vacancy():
    """Move existing unassigned teachers once, without changing real teachers into vacancies."""
    with _planner_lock:
        if state.get("planner_unassigned_vacancy_migrated"):
            return
        project=_planner_project()
        default=_vacancy_membership(project)
        changed=0
        if default:
            for teacher in project.teachers:
                if not teacher.departments:
                    teacher.departments=list(default);changed+=1
        if changed:
            project.revision+=1;state["planner"]=project.model_dump()
        state["planner_unassigned_vacancy_migrated"]=True
        _save_state()


@app.get("/api/admin/planner")
def planner_get(_: None = Depends(require_admin)) -> dict:
    project = _planner_project()
    return {"project": project.model_dump(), "issues": planner.issues(project, state.get("bell_schedule"), complete=True)}


@app.put("/api/admin/planner")
def planner_save(project: planner.Project, _: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        if project.revision != _planner_project().revision:
            raise HTTPException(status_code=409, detail="Черновик изменён в другом окне. Обновите конструктор перед сохранением.")
        try:
            normalize_project_teachers(project)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        errors = planner.references(project)
        if errors:
            raise HTTPException(status_code=422, detail=" ".join(errors[:5]))
        previous_project = _planner_project()
        old_teacher_names={t.name for t in previous_project.teachers}
        for teacher in project.teachers:
            if teacher.name not in old_teacher_names and not teacher.departments:teacher.departments=_vacancy_membership(project)
        vacancy_names={t.name for t in project.teachers if t.is_vacancy}
        vacancy_loads={l.id for l in project.loads if l.teacher in vacancy_names}
        if any(x.load_id in vacancy_loads for x in project.placements):raise HTTPException(422,"Перед расстановкой назначьте учителя на вакансию.")
        old_groups={(g.class_name,g.name.casefold()) for g in previous_project.groups}
        new_groups={(g.class_name,g.name.casefold()) for g in project.groups}
        for load in project.loads:
            if load.group and (load.class_name,load.group.casefold()) in old_groups-new_groups:
                raise HTTPException(409, "Нельзя удалить группу с учебной нагрузкой. Сначала измените нагрузку.")
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


@app.post("/api/admin/planner/catalog-file/{kind}/preview")
async def preview_catalog_file(kind: str, file: UploadFile = File(...), _: None = Depends(require_admin)) -> dict:
    if kind not in ("teachers","rooms"):raise HTTPException(404,"Неизвестный справочник")
    filename=file.filename or ""
    if filename.rsplit(".",1)[-1].lower() not in {"csv","xls","xlsx","xlsm","xml","ods"}:raise HTTPException(422,"Поддерживаются CSV, XLS, XLSX, XLSM, ODS и Excel XML.")
    buf=await file.read(10*1024*1024+1)
    if len(buf)>10*1024*1024:raise HTTPException(413,"Файл больше 10 МБ.")
    try:names=catalog_file.parse(buf,filename,kind)
    except (ParseError,ValueError) as exc:raise HTTPException(422,str(exc)) from exc
    if kind=="teachers":names=[normalize_teacher_initials(name) for name in names]
    with _planner_lock:
        p=_planner_project();seen={x.name.casefold() for x in getattr(p,kind)};added=[];duplicates=[]
        for name in names:
            if name.casefold() in seen:duplicates.append(name)
            else:added.append(name);seen.add(name.casefold())
        if len(getattr(p,kind))+len(added)>200:raise HTTPException(422,"В справочнике допускается не более 200 записей; сократите файл перед загрузкой.")
        return {"revision":p.revision,"added":added,"duplicates":duplicates}


class CatalogFileImport(BaseModel):
    revision: int = Field(ge=0)
    names: list[str] = Field(min_length=1,max_length=200)


@app.post("/api/admin/planner/catalog-file/{kind}/apply")
def apply_catalog_file(kind: str, body: CatalogFileImport, _: None = Depends(require_admin)) -> dict:
    if kind not in ("teachers","rooms"):raise HTTPException(404,"Неизвестный справочник")
    with _planner_lock:
        p=_planner_project().model_copy(deep=True)
        if p.revision!=body.revision:raise HTTPException(409,"Черновик изменился. Проверьте файл заново.")
        existing={x.name.casefold() for x in getattr(p,kind)};added=[]
        for raw in body.names:
            name=" ".join(raw.split())
            if kind=="teachers":name=normalize_teacher_initials(name)
            if not name or len(name)>80:raise HTTPException(422,"Проверьте названия в таблице.")
            if name.casefold() not in existing:
                getattr(p,kind).append(planner.Teacher(name=name,departments=_vacancy_membership(p)) if kind=="teachers" else planner.Room(name=name))
                existing.add(name.casefold());added.append(name)
        if len(getattr(p,kind))>200:raise HTTPException(422,"В справочнике допускается не более 200 записей.")
        if added:
            p.revision+=1;state["planner"]=p.model_dump();_save_state()
        return {"project":p.model_dump(),"issues":planner.issues(p,state.get("bell_schedule"),complete=True),"added":added}


@app.get("/api/schedule/load-template.csv")
def download_load_template() -> Response:
    out=io.StringIO(newline="")
    writer=csv.writer(out,delimiter=";",lineterminator="\r\n")
    writer.writerow(["ФИО учителя","Предмет","Класс","Количество часов в неделю"])
    writer.writerow(["Иванова И.И.","Математика","5а",4])
    writer.writerow(["Иванова И.И.","Математика","5б",4])
    writer.writerow(["Петров П.П.","Физика","7а",2])
    return Response(content=out.getvalue().encode("utf-8-sig"),media_type="text/csv; charset=utf-8",headers={"Content-Disposition":'attachment; filename="workload-template.csv"'})


@app.post("/api/admin/planner/load-import/preview")
async def preview_load_import(file: UploadFile = File(...), _: None = Depends(require_admin)) -> dict:
    name=file.filename or ""
    if name.rsplit(".",1)[-1].lower() not in {"csv","xls","xlsx","xlsm","xml","ods"}:raise HTTPException(422,"Поддерживаются CSV, XLS, XLSX, XLSM, ODS и Excel XML.")
    buf=await file.read(10*1024*1024+1)
    if len(buf)>10*1024*1024:raise HTTPException(413,"Файл больше 10 МБ.")
    try:rows=load_import.parse(buf,name)
    except (ParseError,ValueError) as exc:raise HTTPException(422,str(exc)) from exc
    with _planner_lock:
        p=_planner_project()
        choices={"class_name":[x.name for x in p.classes],"teacher":[x.name for x in p.teachers],"subject":[x.name for x in p.subjects]}
        for row in rows:row["matches"]={k:load_import.match(row[k],v) for k,v in choices.items()}
        return {"revision":p.revision,"rows":rows,"choices":choices}


def schedule_load_candidates(project, data):
    rows,skipped=schedule_load_import.from_schedule(data,normalize_teacher_initials)
    # Preserve existing/manual/imported loads, including conflicting group layouts.
    existing={}
    for load in project.loads:
        key=(load.class_name.casefold(),normalize_teacher_initials(load.teacher).casefold(),load.subject.casefold())
        existing.setdefault(key,[]).append(load.group.casefold())
    additions=[];duplicates=[]
    for row in rows:
        key=(row["class_name"].casefold(),row["teacher"].casefold(),row["subject"].casefold())
        groups=existing.get(key,[]);group=row["group"].casefold()
        if group in groups:
            duplicates.append(row);continue
        if groups and (row.get('inferred') or not group or '' in groups):
            skipped.append(f"{row['class_name']}, {row['subject']}, {row['teacher']}: в черновике уже есть нагрузка с несовместимым разделением на группы.");continue
        additions.append(row);existing.setdefault(key,[]).append(group)
    return additions,duplicates,skipped


@app.get("/api/admin/planner/schedule-load/preview")
def preview_schedule_load(_: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        data=schedule_map.snapshot(state);project=_planner_project()
        rows,duplicates,skipped=schedule_load_candidates(project,data)
        return {"revision":project.revision,"schedule_fingerprint":map_fingerprint(data),"rows":rows,"duplicates":duplicates,"skipped":skipped}


class ScheduleLoadImport(BaseModel):
    revision: int = Field(ge=0)
    schedule_fingerprint: str = Field(min_length=64,max_length=64)


@app.post("/api/admin/planner/schedule-load/apply")
def apply_schedule_load(body: ScheduleLoadImport, _: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        p=_planner_project().model_copy(deep=True);data=schedule_map.snapshot(state)
        if p.revision!=body.revision or map_fingerprint(data)!=body.schedule_fingerprint:raise HTTPException(409,"Конструктор или опубликованное расписание изменились. Обновите предпросмотр.")
        rows,duplicates,skipped=schedule_load_candidates(p,data)
        classes={x.name.casefold():x.name for x in p.classes};teachers={normalize_teacher_initials(x.name).casefold():x.name for x in p.teachers};subjects={x.name.casefold():x.name for x in p.subjects};groups={(g.class_name.casefold(),g.name.casefold()):g.name for g in p.groups}
        second={x.casefold() for x in (data.get("second_shift_classes") or [])}
        for row in rows:
            ck=row["class_name"].casefold();tk=row["teacher"].casefold();sk=row["subject"].casefold()
            if ck not in classes:
                p.classes.append(planner.SchoolClass(name=row["class_name"],shift=2 if ck in second else 1));classes[ck]=row["class_name"]
            if tk not in teachers:p.teachers.append(planner.Teacher(name=row["teacher"],departments=_vacancy_membership(p)));teachers[tk]=row["teacher"]
            if sk not in subjects:p.subjects.append(planner.Named(name=row["subject"]));subjects[sk]=row["subject"]
            cls=classes[ck];group=row["group"];gk=(cls.casefold(),group.casefold())
            if group and gk not in groups:p.groups.append(planner.ClassGroup(name=group,class_name=cls,inferred=row.get("inferred",False)));groups[gk]=group
            p.loads.append(planner.Load(id=secrets.token_hex(16),class_name=cls,teacher=teachers[tk],subject=subjects[sk],group=groups[gk] if group else '',room='',per_week=row["per_week"],max_per_day=row["max_per_day"]))
        if rows:
            try:p=planner.Project.model_validate(p.model_dump())
            except ValueError as exc:raise HTTPException(422,"Невозможно добавить нагрузку: превышен предел справочников конструктора.") from exc
            errors=planner.references(p)
            if errors:raise HTTPException(422," ".join(errors[:5]))
            p.revision+=1;state["planner"]=p.model_dump();_save_state()
        return {"project":p.model_dump(),"issues":planner.issues(p,state.get("bell_schedule"),complete=True),"added":len(rows),"duplicates":len(duplicates),"skipped":len(skipped)}


class DepartmentCatalogChange(BaseModel):
    revision: int = Field(ge=0)
    action: Literal['add','rename','delete']
    name: str = Field(default='',max_length=80)
    new_name: str = Field(default='',max_length=80)


@app.post("/api/admin/planner/department-catalog")
def change_department_catalog(body: DepartmentCatalogChange, _: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        p=_planner_project().model_copy(deep=True)
        if p.revision!=body.revision:raise HTTPException(409,"Черновик изменился. Обновите конструктор.")
        name=' '.join(body.name.split());new=' '.join(body.new_name.split())
        if body.action=='add':
            if not new or len(new)>80:raise HTTPException(422,"Укажите название кафедры.")
            if new in ('__none__','__create__') or any(d.name.casefold()==new.casefold() for d in p.departments):raise HTTPException(409,"Такая кафедра уже существует или название зарезервировано.")
            if len(p.departments)>=100:raise HTTPException(422,"Достигнут предел кафедр.")
            p.departments.append(planner.Named(name=new))
            if not p.vacancy_department and new.casefold()=='вакансия':p.vacancy_department=new
        else:
            item=next((d for d in p.departments if d.name==name),None)
            if not item:raise HTTPException(404,"Кафедра не найдена.")
            if body.action=='rename':
                if not new or len(new)>80:raise HTTPException(422,"Укажите название кафедры.")
                if new in ('__none__','__create__') or any(d is not item and d.name.casefold()==new.casefold() for d in p.departments):raise HTTPException(409,"Такая кафедра уже существует или название зарезервировано.")
                item.name=new
                if p.vacancy_department==name:p.vacancy_department=new
                for teacher in p.teachers:teacher.departments=[new if d==name else d for d in teacher.departments]
            else:
                fallback=_vacancy_membership(p) if name!=p.vacancy_department else []
                for teacher in p.teachers:
                    if name not in teacher.departments:continue
                    teacher.departments=[d for d in teacher.departments if d!=name]
                    if not teacher.departments:teacher.departments=list(fallback)
                p.departments.remove(item)
                if p.vacancy_department==name:p.vacancy_department=''
        p.revision+=1;state['planner']=p.model_dump();_save_state()
        return {"project":p.model_dump(),"issues":planner.issues(p,state.get("bell_schedule"),complete=True)}


class DepartmentAssignment(BaseModel):
    revision: int = Field(ge=0)
    teacher: str = Field(min_length=1,max_length=80)
    departments: list[Department] = Field(max_length=100)


@app.post("/api/admin/planner/teacher-departments")
def set_teacher_departments(body: DepartmentAssignment, _: None = Depends(require_admin)) -> dict:
    if len(set(body.departments))!=len(body.departments):raise HTTPException(422,"Кафедра указана повторно.")
    with _planner_lock:
        p=_planner_project().model_copy(deep=True)
        if p.revision!=body.revision:raise HTTPException(409,"Черновик изменился. Обновите конструктор.")
        teacher=next((t for t in p.teachers if t.name==body.teacher),None)
        if not teacher:raise HTTPException(404,"Учитель не найден.")
        if any(d not in {x.name for x in p.departments} for d in body.departments):raise HTTPException(422,"Кафедра отсутствует в справочнике.")
        teacher.departments=list(body.departments) or _vacancy_membership(p);p.revision+=1
        state["planner"]=p.model_dump();_save_state()
        return {"project":p.model_dump(),"issues":planner.issues(p,state.get("bell_schedule"),complete=True)}


class ClearDepartmentLoad(BaseModel):
    revision: int = Field(ge=0)
    department: Department


@app.post("/api/admin/planner/department-load/clear")
def clear_department_load(body: ClearDepartmentLoad, _: None = Depends(require_admin)) -> dict:
    """Удалить только черновую нагрузку учителей кафедры, без частичного удаления."""
    with _planner_lock:
        p=_planner_project().model_copy(deep=True)
        if p.revision!=body.revision:raise HTTPException(409,"Черновик изменился. Обновите конструктор и повторите проверку.")
        if body.department not in {d.name for d in p.departments}:raise HTTPException(422,"Кафедра отсутствует в справочнике.")
        teachers={t.name for t in p.teachers if body.department in t.departments}
        selected=[load for load in p.loads if load.teacher in teachers]
        ids={load.id for load in selected}
        placed=[entry for entry in p.placements if entry.load_id in ids]
        if placed:raise HTTPException(409,f"Очистка не выполнена: в черновике расставлено уроков по нагрузке кафедры: {len(placed)}. Сначала снимите их; другие записи не изменены.")
        if selected:
            p.loads=[load for load in p.loads if load.id not in ids]
            p.revision+=1;state["planner"]=p.model_dump();_save_state()
        return {"project":p.model_dump(),"issues":planner.issues(p,state.get("bell_schedule"),complete=True),"removed":len(selected)}


class ClearAllLoad(BaseModel):
    revision: int = Field(ge=0)


@app.post("/api/admin/planner/all-load/clear")
def clear_all_load(body: ClearAllLoad, _: None = Depends(require_admin)) -> dict:
    """Атомарно удалить всю нагрузку черновика, включая учителей без кафедры."""
    with _planner_lock:
        p=_planner_project().model_copy(deep=True)
        if p.revision!=body.revision:raise HTTPException(409,"Черновик изменился. Обновите конструктор и повторите проверку.")
        ids={load.id for load in p.loads}
        placed=sum(1 for entry in p.placements if entry.load_id in ids)
        if placed:raise HTTPException(409,f"Очистка не выполнена: в черновике расставлено уроков по нагрузке: {placed}. Сначала снимите их; данные не изменены.")
        removed=len(p.loads)
        if removed:
            p.loads=[];p.revision+=1;state["planner"]=p.model_dump();_save_state()
        return {"project":p.model_dump(),"issues":planner.issues(p,state.get("bell_schedule"),complete=True),"removed":removed}


@app.post("/api/admin/planner/department-file/preview")
async def preview_department_file(file: UploadFile = File(...), _: None = Depends(require_admin)) -> dict:
    filename=file.filename or ''
    if filename.rsplit('.',1)[-1].lower() not in {'csv','xls','xlsx','xlsm','xml','ods'}:raise HTTPException(422,"Неподдерживаемый формат файла.")
    buf=await file.read(10*1024*1024+1)
    if len(buf)>10*1024*1024:raise HTTPException(413,"Файл больше 10 МБ.")
    try:names,skipped=departments.read_teachers(buf,filename)
    except (ParseError,ValueError) as exc:raise HTTPException(422,str(exc)) from exc
    with _planner_lock:
        p=_planner_project();choices=[t.name for t in p.teachers]
        rows=[]
        for name in names:
            match=load_import.match(normalize_teacher_initials(name),choices)
            rows.append({"source":name,"match":match})
        return {"revision":p.revision,"rows":rows,"skipped":skipped,"teachers":choices}


class DepartmentImportRow(BaseModel):
    source: str = Field(min_length=1,max_length=80)
    teacher: str = Field(max_length=80)  # Existing exact name, or empty for an explicitly requested new teacher.


class DepartmentImport(BaseModel):
    revision: int = Field(ge=0)
    department: Department
    rows: list[DepartmentImportRow] = Field(min_length=1,max_length=200)


@app.post("/api/admin/planner/department-file/apply")
def apply_department_file(body: DepartmentImport, _: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        p=_planner_project().model_copy(deep=True)
        if p.revision!=body.revision:raise HTTPException(409,"Черновик изменился. Проверьте файл заново.")
        if body.department not in {d.name for d in p.departments}:raise HTTPException(422,"Кафедра отсутствует в справочнике.")
        byname={t.name:t for t in p.teachers};existing={t.name.casefold():t for t in p.teachers};seen=set();assigned=created=0
        for row in body.rows:
            if row.teacher:
                teacher=byname.get(row.teacher)
                if not teacher:raise HTTPException(422,"Выберите учителя из справочника.")
            else:
                name=normalize_teacher_initials(row.source)
                if len(name)>80 or not re.fullmatch(r'[А-ЯЁа-яёA-Za-z-]+\s+[А-ЯЁA-Zа-яёa-z.\s-]+',name):raise HTTPException(422,"Некорректное ФИО нового учителя.")
                if name.casefold() in existing:raise HTTPException(409,"Такой учитель уже есть; выберите его из справочника.")
                if len(p.teachers)>=200:raise HTTPException(422,"Превышен предел учителей.")
                teacher=planner.Teacher(name=name);p.teachers.append(teacher);existing[name.casefold()]=teacher;byname[name]=teacher;created+=1
            if teacher.name in seen:raise HTTPException(422,"Один учитель выбран в нескольких строках. Исправьте сопоставление.")
            seen.add(teacher.name)
            if body.department not in teacher.departments:teacher.departments.append(body.department);assigned+=1
        if assigned or created:
            p.revision+=1;state["planner"]=p.model_dump();_save_state()
        return {"project":p.model_dump(),"issues":planner.issues(p,state.get("bell_schedule"),complete=True),"assigned":assigned,"created":created}


class LoadImportRow(BaseModel):
    class_name: str
    teacher: str
    subject: str
    per_week: int = Field(ge=1,le=36)


class LoadImportRequest(BaseModel):
    revision: int = Field(ge=0)
    rows: list[LoadImportRow] = Field(min_length=1,max_length=5000)


@app.post("/api/admin/planner/load-import/apply")
def apply_load_import(body: LoadImportRequest, _: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        p=_planner_project().model_copy(deep=True)
        if p.revision!=body.revision:raise HTTPException(409,"Черновик изменился. Загрузите файл заново.")
        sets={"class_name":{x.name for x in p.classes},"teacher":{x.name for x in p.teachers},"subject":{x.name for x in p.subjects}}
        seen=set()
        for row in body.rows:
            if any(getattr(row,k) not in names for k,names in sets.items()):raise HTTPException(422,"Выберите существующие класс, учителя и предмет для каждой строки.")
            key=(row.class_name,row.subject,row.teacher)
            if key in seen:raise HTTPException(422,f"Повтор нагрузки: {row.class_name}, {row.subject}, {row.teacher}. Проверьте файл.")
            seen.add(key)
        existing={(x.class_name,x.subject,x.teacher):x for x in p.loads}
        if len(existing)!=len(p.loads):raise HTTPException(409,"В существующей нагрузке есть одинаковые записи. Устраните дубликаты перед импортом.")
        placed={x.load_id for x in p.placements};added=updated=0;affected=set()
        for row in body.rows:
            key=(row.class_name,row.subject,row.teacher);affected.add(key[:2])
            if key in existing:
                load=existing[key]
                if load.per_week!=row.per_week and load.id in placed:raise HTTPException(409,f"Нагрузка {row.class_name} · {row.teacher} уже расставлена. Сначала снимите её уроки.")
                if load.per_week!=row.per_week:load.per_week=row.per_week;updated+=1
            else:
                load=planner.Load(id=secrets.token_hex(16),class_name=row.class_name,subject=row.subject,teacher=row.teacher,room="",per_week=row.per_week)
                p.loads.append(load);existing[key]=load;added+=1
        for cls,subject in affected:
            loads=[l for l in p.loads if l.class_name==cls and l.subject==subject]
            if len(loads)<2:continue
            used={l.group.casefold() for l in loads if l.group}
            if len(used)!=sum(bool(l.group) for l in loads):raise HTTPException(409,f"В {cls}, {subject} повторяется группа. Исправьте существующую нагрузку.")
            for load in loads:
                if load.group:continue
                if load.id in placed:raise HTTPException(409,f"Уроки {cls}, {subject} уже расставлены. Снимите их перед разделением на группы.")
                n=1
                while f"{n} группа".casefold() in used:n+=1
                group=f"{n} группа";used.add(group.casefold());load.group=group
                if not any(g.class_name==cls and g.name.casefold()==group.casefold() for g in p.groups):p.groups.append(planner.ClassGroup(name=group,class_name=cls,inferred=True))
        try:p=planner.Project.model_validate(p.model_dump())
        except ValueError as exc:raise HTTPException(422,"Превышены ограничения проекта.") from exc
        errors=planner.references(p)
        if errors:raise HTTPException(422," ".join(errors[:5]))
        p.revision+=1;state["planner"]=p.model_dump();_save_state()
        return {"added":added,"updated":updated,"project":p.model_dump(),"issues":planner.issues(p,state.get("bell_schedule"),complete=True)}


class NewTeacherLoad(BaseModel):
    revision: int = Field(ge=0)
    teacher: str = Field(min_length=1,max_length=80)
    class_name: str = Field(min_length=1,max_length=80)
    subject: str = Field(min_length=1,max_length=80)
    create_teacher: bool = False
    vacancy: bool = False
    create_subject: bool = False
    department: Department | None = None
    group: str = Field(default='',max_length=80)
    room: str = Field(default='',max_length=80)
    per_week: int = Field(ge=1,le=36)
    max_per_day: int = Field(default=12,ge=1,le=12)


@app.post("/api/admin/planner/teacher-load-add")
def add_teacher_load(body: NewTeacherLoad, _: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        p=_planner_project().model_copy(deep=True)
        if p.revision!=body.revision:raise HTTPException(409,"Черновик изменился. Обновите конструктор.")
        if body.department and body.department not in {d.name for d in p.departments}:raise HTTPException(422,"Кафедра отсутствует в справочнике.")
        if body.vacancy:
            existing=next((t for t in p.teachers if t.is_vacancy),None)
            if existing:teacher=existing.name
            else:
                if any(t.name.casefold()=='вакансия' for t in p.teachers):raise HTTPException(409,"В справочнике уже есть учитель с именем «Вакансия». Переименуйте его перед созданием вакансии.")
                if len(p.teachers)>=200:raise HTTPException(422,"Достигнут предел учителей.")
                teacher='Вакансия';p.teachers.append(planner.Teacher(name=teacher,is_vacancy=True,departments=[p.vacancy_department] if p.vacancy_department else []))
        else:teacher=normalize_teacher_initials(body.teacher) if body.create_teacher else body.teacher
        subject=' '.join(body.subject.split()) if body.create_subject else body.subject
        if body.class_name not in {c.name for c in p.classes}:raise HTTPException(422,"Выберите класс из справочника.")
        if body.create_teacher and not body.vacancy:
            if not teacher or len(teacher)>80:raise HTTPException(422,"Укажите ФИО учителя.")
            if any(normalize_teacher_initials(t.name).casefold()==teacher.casefold() for t in p.teachers):raise HTTPException(409,"Такой учитель уже есть в справочнике. Выберите его из списка.")
            if len(p.teachers)>=200:raise HTTPException(422,"Достигнут предел учителей.")
            p.teachers.append(planner.Teacher(name=teacher,departments=[body.department] if body.department else _vacancy_membership(p)))
        elif teacher not in {t.name for t in p.teachers}:raise HTTPException(422,"Выберите учителя из справочника.")
        if body.create_subject:
            if not subject or len(subject)>80:raise HTTPException(422,"Укажите название предмета.")
            if any(' '.join(x.name.split()).casefold()==subject.casefold() for x in p.subjects):raise HTTPException(409,"Такой предмет уже есть в справочнике. Выберите его из списка.")
            if len(p.subjects)>=200:raise HTTPException(422,"Достигнут предел предметов.")
            p.subjects.append(planner.Named(name=subject))
        elif subject not in {x.name for x in p.subjects}:raise HTTPException(422,"Выберите предмет из справочника.")
        if body.room and body.room not in {r.name for r in p.rooms}:raise HTTPException(422,"Кабинет отсутствует в справочнике.")
        if body.group and not any(g.class_name==body.class_name and g.name==body.group for g in p.groups):raise HTTPException(422,"Группа отсутствует в справочнике этого класса.")
        peers=[x for x in p.loads if x.class_name==body.class_name and x.subject==subject]
        is_vacancy=any(t.name==teacher and t.is_vacancy for t in p.teachers)
        if any(x.teacher==teacher and (not is_vacancy or x.group.casefold()==body.group.casefold()) for x in peers):raise HTTPException(409,"Такая нагрузка у учителя или вакансии уже есть. Измените существующую запись.")
        if peers and (not body.group or any(not x.group for x in peers)):raise HTTPException(409,"Для нескольких учителей одного предмета укажите разные группы во всех записях нагрузки.")
        if body.group and any(x.group.casefold()==body.group.casefold() for x in peers):raise HTTPException(409,"Эта группа уже назначена другому учителю по этому предмету.")
        if len(p.loads)>=10000:raise HTTPException(422,"Достигнут предел записей нагрузки.")
        p.loads.append(planner.Load(id=secrets.token_hex(16),teacher=teacher,class_name=body.class_name,subject=subject,group=body.group,room=body.room,per_week=body.per_week,max_per_day=body.max_per_day))
        p.revision+=1;state['planner']=p.model_dump();_save_state()
        return {"project":p.model_dump(),"issues":planner.issues(p,state.get("bell_schedule"),complete=True),"teacher":teacher}


class DeleteTeacherLoad(BaseModel):
    revision: int = Field(ge=0)
    load_id: str = Field(min_length=1,max_length=80)


@app.post("/api/admin/planner/teacher-load-delete")
def delete_teacher_load(body: DeleteTeacherLoad, _: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        p=_planner_project().model_copy(deep=True)
        if p.revision!=body.revision:raise HTTPException(409,"Черновик изменился. Обновите конструктор.")
        load=next((x for x in p.loads if x.id==body.load_id),None)
        if not load:raise HTTPException(404,"Запись нагрузки не найдена.")
        if any(x.load_id==load.id for x in p.placements):raise HTTPException(409,"Сначала снимите расставленные уроки этой нагрузки. Опубликованное расписание не изменится.")
        p.loads.remove(load);p.revision+=1;state['planner']=p.model_dump();_save_state()
        return {"project":p.model_dump(),"issues":planner.issues(p,state.get("bell_schedule"),complete=True)}


class LoadChange(BaseModel):
    revision: int = Field(ge=0)
    load_id: str
    group: str = Field(max_length=80)
    room: str = Field(max_length=80)
    class_name: str | None = Field(default=None,min_length=1,max_length=80)
    teacher: str | None = Field(default=None,min_length=1,max_length=80)
    subject: str | None = Field(default=None,min_length=1,max_length=80)
    per_week: int | None = Field(default=None,ge=1,le=36)
    max_per_day: int | None = Field(default=None,ge=1,le=12)


@app.post("/api/admin/planner/load-change")
def change_load(body: LoadChange, _: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        p=_planner_project().model_copy(deep=True)
        if p.revision!=body.revision:raise HTTPException(409,"Черновик изменился. Обновите конструктор.")
        load=next((x for x in p.loads if x.id==body.load_id),None)
        if not load:raise HTTPException(404,"Нагрузка не найдена")
        if body.room and body.room not in {r.name for r in p.rooms}:raise HTTPException(422,"Кабинет отсутствует в справочнике")
        cls=body.class_name if body.class_name is not None else load.class_name
        teacher=body.teacher if body.teacher is not None else load.teacher
        subject=body.subject if body.subject is not None else load.subject
        hours=body.per_week if body.per_week is not None else load.per_week
        daily=body.max_per_day if body.max_per_day is not None else load.max_per_day
        if cls not in {x.name for x in p.classes} or teacher not in {x.name for x in p.teachers} or subject not in {x.name for x in p.subjects}:raise HTTPException(422,"Выберите существующие класс, учителя и предмет.")
        identity_changed=(cls,teacher,subject)!=(load.class_name,load.teacher,load.subject)
        if (identity_changed or hours!=load.per_week) and any(x.load_id==load.id for x in p.placements):raise HTTPException(409,"Для изменения класса, учителя, предмета или часов сначала снимите расставленные уроки этой нагрузки.")
        if identity_changed and any(x.id!=load.id and (x.class_name,x.teacher,x.subject)==(cls,teacher,subject) for x in p.loads):raise HTTPException(409,"Такая нагрузка для класса, предмета и учителя уже существует.")
        peers=[x for x in p.loads if x.class_name==cls and x.subject==subject and x.id!=load.id]
        if body.group and not any(g.class_name==cls and g.name==body.group for g in p.groups):raise HTTPException(422,"Группа отсутствует в справочнике")
        if peers and not body.group:raise HTTPException(422,"Для параллельных учителей выберите группу.")
        other=next((x for x in peers if x.group==body.group and body.group),None)
        if other and (identity_changed or not load.group):raise HTTPException(409,"Эта группа уже назначена другому учителю. Выберите свободную группу.")
        def conflicts(project):
            return Counter(issue for issue in planner.issues(project,state.get("bell_schedule")) if not issue.startswith("Укажите кабинет для "))
        before=conflicts(p)
        if other:other.group=load.group
        if body.room != load.room:
            for placement in p.placements:
                if placement.load_id == load.id:
                    placement.room = "" if body.room else (load.room or placement.room)
        load.class_name=cls;load.teacher=teacher;load.subject=subject;load.per_week=hours;load.max_per_day=daily
        load.group=body.group;load.room=body.room
        after=conflicts(p)
        added=list((after-before).elements())
        if added:raise HTTPException(409,"Изменение создаёт конфликт: "+added[0])
        p.revision+=1;state["planner"]=p.model_dump();_save_state()
        return {"project":p.model_dump(),"issues":planner.issues(p,state.get("bell_schedule"),complete=True)}


class TeacherLoadTransfer(BaseModel):
    revision: int = Field(ge=0)
    source: str = Field(min_length=1,max_length=80)
    target: str = Field(min_length=1,max_length=80)


@app.post("/api/admin/planner/transfer-teacher-load")
def transfer_teacher_load(body: TeacherLoadTransfer, _: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        p=_planner_project().model_copy(deep=True)
        if p.revision!=body.revision:raise HTTPException(409,"Черновик изменился. Обновите конструктор.")
        names={teacher.name for teacher in p.teachers}
        if body.source not in names or body.target not in names:raise HTTPException(422,"Выберите учителей из справочника.")
        if body.source==body.target:raise HTTPException(422,"Выберите разных учителей.")
        transferring=[load for load in p.loads if load.teacher==body.source]
        if not transferring:raise HTTPException(422,"У выбранного учителя нет нагрузки в конструкторе.")
        target_keys={(load.class_name,load.subject) for load in p.loads if load.teacher==body.target}
        duplicate=next((load for load in transferring if (load.class_name,load.subject) in target_keys),None)
        if duplicate:raise HTTPException(409,f"У нового учителя уже есть нагрузка {duplicate.class_name} · {duplicate.subject}. Сначала разрешите совпадение в списке нагрузки.")
        ids={load.id for load in transferring}
        placed=[entry for entry in p.placements if entry.load_id in ids]
        bells=state.get("bell_schedule")
        classes={cls.name:cls for cls in p.classes}
        for entry in placed:
            load=next(load for load in transferring if load.id==entry.load_id)
            if not planner.period(bells,entry.day,classes[load.class_name].shift,entry.lesson):
                raise HTTPException(422,"Нельзя проверить перенос расставленных уроков: не хватает времени звонков.")
        load_by_id={load.id:load for load in p.loads}
        affected_days={entry.day for entry in placed}
        for entry in p.placements:
            other=load_by_id[entry.load_id]
            if other.teacher==body.target and entry.day in affected_days and not planner.period(bells,entry.day,classes[other.class_name].shift,entry.lesson):
                raise HTTPException(422,"Нельзя проверить занятость нового учителя: не хватает времени звонков.")
        target_teacher=next(t for t in p.teachers if t.name==body.target)
        for slot in target_teacher.unavailable:
            if any(entry.day==slot.day for entry in placed) and not planner.period(bells,slot.day,slot.shift,slot.lesson):
                raise HTTPException(422,"Нельзя проверить недоступность нового учителя: не хватает времени звонков.")
        before=Counter(planner.issues(p,bells))
        for load in transferring:load.teacher=body.target
        added=list((Counter(planner.issues(p,bells))-before).elements())
        if added:raise HTTPException(409,"Передача создаёт конфликт: "+added[0])
        p.revision+=1;state["planner"]=p.model_dump();_save_state()
        return {"project":p.model_dump(),"issues":planner.issues(p,bells,complete=True),"transferred":len(transferring),"placements":len(placed)}


class PlannerRename(BaseModel):
    revision: int = Field(ge=0)
    old_name: str = Field(min_length=1, max_length=80)
    new_name: str = Field(min_length=1, max_length=80)


@app.post("/api/admin/planner/rename/{kind}")
def planner_rename(kind: str, body: PlannerRename, _: None = Depends(require_admin)) -> dict:
    if kind not in ("classes", "teachers", "subjects", "rooms"):
        raise HTTPException(404, "Неизвестный справочник")
    name = " ".join(body.new_name.split())
    if not name:
        raise HTTPException(422, "Название не может быть пустым")
    if kind == "teachers":
        name = normalize_teacher_initials(name)
    with _planner_lock:
        project = _planner_project()
        if body.revision != project.revision:
            raise HTTPException(409, "Черновик изменён в другом окне. Обновите конструктор.")
        entries = getattr(project, kind)
        item = next((x for x in entries if x.name == body.old_name), None)
        if not item:
            raise HTTPException(404, "Запись не найдена")
        if any(x is not item and x.name.casefold() == name.casefold() for x in entries):
            raise HTTPException(422, "Такая запись уже есть в справочнике")
        if name == item.name:
            return {"project":project.model_dump(),"issues":planner.issues(project,state.get("bell_schedule"),complete=True)}
        old_name=item.name
        item.name=name
        if kind == "classes":
            for group in project.groups:
                if group.class_name == old_name:
                    group.class_name = name
        for load in project.loads:
            if kind == "classes" and load.class_name == old_name:
                load.class_name=name
            elif kind == "teachers" and load.teacher == old_name:
                load.teacher=name
            elif kind == "subjects" and load.subject == old_name:
                load.subject=name
            elif kind == "rooms" and load.room == old_name:
                load.room=name
        for rule in project.preferences:
            if kind == "classes" and rule.scope == "class" and rule.scope_value == old_name:
                rule.scope_value = name
            if kind == "subjects":
                if rule.subject == old_name: rule.subject = name
                if rule.next_subject == old_name: rule.next_subject = name
        if kind == "rooms":
            for teacher in project.teachers:
                if teacher.preferred_room == old_name: teacher.preferred_room = name
            for placement in project.placements:
                if placement.room == old_name: placement.room = name
        project.revision += 1
        previous=state.get("planner")
        try:
            with staff_store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if kind == "classes":
                    db.execute("UPDATE users SET homeroom_class=? WHERE role='teacher' AND active=1 AND homeroom_class=?", (name,old_name))
                state["planner"] = project.model_dump()
                _save_state()
        except Exception:
            state["planner"] = previous
            raise
        return {"project":project.model_dump(),"issues":planner.issues(project,state.get("bell_schedule"),complete=True)}


class PlannerGroupRename(BaseModel):
    revision: int = Field(ge=0)
    class_name: str = Field(min_length=1,max_length=80)
    old_name: str = Field(min_length=1,max_length=80)
    new_name: str = Field(min_length=1,max_length=80)


@app.post("/api/admin/planner/rename-group")
def planner_rename_group(body: PlannerGroupRename, _: None = Depends(require_admin)) -> dict:
    name=" ".join(body.new_name.split())
    if not name: raise HTTPException(422,"Укажите название группы")
    with _planner_lock:
        project=_planner_project()
        if body.revision != project.revision: raise HTTPException(409,"Черновик изменён в другом окне. Обновите конструктор.")
        item=next((g for g in project.groups if g.class_name==body.class_name and g.name==body.old_name),None)
        if not item: raise HTTPException(404,"Группа не найдена")
        if any(g is not item and g.class_name==item.class_name and g.name.casefold()==name.casefold() for g in project.groups):
            raise HTTPException(422,"Группа с таким названием уже существует в этом классе")
        for load in project.loads:
            if load.class_name==item.class_name and load.group.casefold()==item.name.casefold(): load.group=name
        item.name=name;item.inferred=False;project.revision+=1
        state["planner"]=project.model_dump();_save_state()
        return {"project":project.model_dump(),"issues":planner.issues(project,state.get("bell_schedule"),complete=True)}


def map_fingerprint(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode("utf-8")).hexdigest()


def map_current():
    published=schedule_map.snapshot(state)
    draft=state.get("schedule_map_draft")
    if draft:
        return draft, draft["base"] != map_fingerprint(published)
    return {"base":map_fingerprint(published),"revision":0,"data":published}, False


WEEKLY_MOVE_SECONDS = 7 * 24 * 60 * 60


def map_entry_at(data, class_name, day, raw):
    return next((e for e in schedule_map.entries(data,class_name) if e["day"]==day and e["raw"]==raw),None)


def active_weekly_moves(now=None):
    """Показываем только неистёкшие отметки, относящиеся к актуальной сетке."""
    now=time.time() if now is None else now
    data=schedule_map.snapshot(state)
    result=[]
    for notice in state.get("weekly_move_notices",[]):
        if notice.get("expires_at",0)<=now: continue
        target=notice.get("target",{})
        current=map_entry_at(data,notice.get("class_name",""),target.get("day"),target.get("raw"))
        if not current or current.get("teachers")!=target.get("teachers") or current.get("subjects")!=target.get("subjects"): continue
        result.append(notice)
    return result


def build_weekly_move_notices(draft, now):
    notices=copy.deepcopy(active_weekly_moves(now))
    for event in draft.get("move_events",[]):
        cls=event["class_name"];source=event["source"]
        index=next((i for i,n in enumerate(notices) if n["class_name"]==cls and n["target"]["day"]==source["day"] and n["target"]["raw"]==source["raw"]),None)
        if event["type"]=="remove":
            if index is not None: notices.pop(index)
            continue
        if index is None:
            notice={"class_name":cls,"source":source}
        else:
            notice=notices.pop(index)
        target=event["target"]
        if (target["day"],target["raw"])==(notice["source"]["day"],notice["source"]["raw"]): continue
        notice.update(target=target,expires_at=now+WEEKLY_MOVE_SECONDS)
        notices.append(notice)
    # An edited or deleted target must not leave an orphaned cancellation marker.
    result=[]
    for notice in notices:
        target=notice["target"]
        current=map_entry_at(draft["data"],notice["class_name"],target["day"],target["raw"])
        if current:
            notice["target"]=current
            result.append(notice)
    return result


def check_map_conflicts(data, class_name, day, shift, lesson, teacher_cell, subject_cell):
    p=schedule_map.period(data,shift,day,lesson)
    start,end=schedule_map.clock(p.get("start")),schedule_map.clock(p.get("end"))
    if start is None or end is None or start>=end:
        raise HTTPException(422,"Для выбранного дня и урока нет времени звонков.")
    names={normalize_teacher_initials(x).casefold() for x in teacher_cell.get("names",[]) if x and x not in {"Классный час","СФУ","Экскурсия"}}
    rooms={" ".join(x.split()).casefold() for cell in (teacher_cell,subject_cell) for x in cell.get("rooms",[]) if x}
    project=_planner_project()
    resources=[("класс",x.name,x.unavailable) for x in project.classes if x.name==class_name]
    resources += [("учитель",x.name,x.unavailable) for x in project.teachers if normalize_teacher_initials(x.name).casefold() in names]
    resources += [("кабинет",x.name,x.unavailable) for x in project.rooms if " ".join(x.name.split()).casefold() in rooms]
    for label,name,unavailable in resources:
        for slot in unavailable:
            if slot.day!=day:continue
            blocked=planner.period(data.get("bell_schedule"),slot.day,slot.shift,slot.lesson)
            if blocked is None:raise HTTPException(422,f"Нельзя проверить ограничение: нет звонков для {label} {name}.")
            if start<blocked[1] and blocked[0]<end:raise HTTPException(409,f"Ограничение: {label} {name} недоступен.")
    classes={c for kind in ("teachers","subjects") for c in (data.get(kind) or {}).get("classes",[])}
    for cls in classes-{class_name}:
        for other in schedule_map.entries(data,cls):
            if other["day"]!=day:continue
            other_names={normalize_teacher_initials(x).casefold() for x in other["teachers"].get("names",[]) if x and x not in {"Классный час","СФУ","Экскурсия"}}
            other_rooms={" ".join(x.split()).casefold() for kind in ("teachers","subjects") for x in other[kind].get("rooms",[]) if x}
            if not (names & other_names or rooms & other_rooms):continue
            other_period=schedule_map.period(data,other["shift"],other["day"],other["lesson"])
            a,b=schedule_map.clock(other_period.get("start")),schedule_map.clock(other_period.get("end"))
            if a is None or b is None:raise HTTPException(422,f"Нельзя проверить конфликт с классом {cls}: нет времени звонков.")
            if start<b and a<end:raise HTTPException(409,f"Конфликт учителя или кабинета с классом {cls}.")


class MapMove(BaseModel):
    revision: int = Field(ge=0)
    class_name: str = Field(min_length=1,max_length=80)
    day: Literal["Пн","Вт","Ср","Чт","Пт","Сб"]
    raw: str = Field(pattern=r"^\d{1,2}$")
    target_day: Literal["Пн","Вт","Ср","Чт","Пт","Сб"]
    target_lesson: int = Field(ge=1,le=12)
    room: str | None = Field(default=None, min_length=1, max_length=80)


@app.get("/api/admin/schedule-map")
def read_schedule_map(class_name: str = "", all_entries: bool = False, _: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        draft,stale=map_current();data=draft["data"]
        classes=list(dict.fromkeys(c for kind in ("teachers","subjects") for c in (data.get(kind) or {}).get("classes",[])))
        if class_name and class_name not in classes: raise HTTPException(404,"Класс не найден")
        if all_entries:
            current=[{**entry,"class_name":cls} for cls in classes for entry in schedule_map.entries(data,cls)]
            published=schedule_map.snapshot(state)
            original=[{**entry,"class_name":cls} for cls in classes for entry in schedule_map.entries(published,cls)]
            key=lambda e:(e["class_name"],e["day"],e["raw"])
            original_by_key={key(e):e for e in original};current_by_key={key(e):e for e in current}
            entries=[{**e,"change":"added" if original_by_key.get(key(e))!=e else ""} for e in current]
            entries += [{**e,"change":"removed"} for e in original if current_by_key.get(key(e))!=e]
            for notice in active_weekly_moves():
                cls=notice["class_name"];source={**notice["source"],"class_name":cls,"change":"removed"};target=notice["target"]
                if not any(key(e)==key(source) and e.get("change")=="removed" and e["teachers"]==source["teachers"] and e["subjects"]==source["subjects"] for e in entries): entries.append(source)
                for e in entries:
                    if e["class_name"]==cls and e["day"]==target["day"] and e["raw"]==target["raw"] and e.get("change")!="removed": e["change"]="added"
        else: entries=schedule_map.entries(data,class_name) if class_name else []
        expirations=[n["expires_at"] for n in active_weekly_moves()]
        return {"revision":draft["revision"],"stale":stale,"classes":classes,"entries":entries,"has_changes":bool(state.get("schedule_map_draft")),"weekly_expires_at":min(expirations) if expirations else None}


def map_can_change_room(entry):
    rooms={" ".join(r.split()).casefold() for k in ("teachers", "subjects") for r in entry[k].get("rooms", []) if r}
    return len(entry["teachers"].get("names", [])) <= 1 and len(rooms) <= 1 and all(len(entry[k].get("groups", [])) <= 1 for k in ("teachers", "subjects"))


@app.post("/api/admin/schedule-map/available-rooms")
def available_map_rooms(body: MapMove, _: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        draft,stale=map_current()
        if stale or body.revision != draft["revision"]: raise HTTPException(409,"Расписание или карта изменились. Обновите данные.")
        data=draft["data"]
        classes={c for kind in ("teachers","subjects") for c in (data.get(kind) or {}).get("classes",[])}
        if body.class_name not in classes: raise HTTPException(404,"Класс не найден")
        entry=next((e for e in schedule_map.entries(data,body.class_name) if e["day"]==body.day and e["raw"]==body.raw),None)
        if not entry: raise HTTPException(404,"Урок не найден")
        if not map_can_change_room(entry): return {"rooms":[],"can_change":False}
        shift=2 if body.class_name in (data.get("second_shift_classes") or []) else 1
        p=schedule_map.period(data,shift,body.target_day,body.target_lesson)
        start,end=schedule_map.clock(p.get("start")),schedule_map.clock(p.get("end"))
        if start is None or end is None or start>=end: raise HTTPException(422,"Для выбранного дня и урока нет времени звонков.")
        names=[r.name for r in _planner_project().rooms]
        names += [r for cls in classes for e in schedule_map.entries(data,cls) for kind in ("teachers","subjects") for r in e[kind].get("rooms",[]) if r]
        names=list({" ".join(name.split()).casefold():" ".join(name.split()) for name in names if name and name.strip()}.values())
        free=[]
        for room in names:
            try: check_map_conflicts(data,body.class_name,body.target_day,shift,body.target_lesson,{"names":[],"rooms":[room]},{})
            except HTTPException as error:
                if error.status_code == 409: continue
                raise
            free.append(room)
        return {"rooms":sorted(free,key=str.casefold),"can_change":True}


@app.post("/api/admin/schedule-map/move")
def move_schedule_map(body: MapMove, _: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        draft,stale=map_current()
        if stale: raise HTTPException(409,"Опубликованное расписание изменилось. Обновите карту, чтобы не потерять новые данные.")
        if draft["revision"]!=body.revision: raise HTTPException(409,"Карта изменилась в другом окне. Обновите страницу.")
        data=copy.deepcopy(draft["data"])
        valid_classes={c for kind in ("teachers","subjects") for c in (data.get(kind) or {}).get("classes",[])}
        if body.class_name not in valid_classes: raise HTTPException(404,"Класс не найден")
        entry=next((e for e in schedule_map.entries(data,body.class_name) if e["day"]==body.day and e["raw"]==body.raw),None)
        if not entry: raise HTTPException(404,"Урок не найден")
        original_entry=copy.deepcopy(entry)
        target_raw=schedule_map.destination(data,body.class_name,body.target_day,body.target_lesson)
        same=body.day==body.target_day and body.raw==target_raw
        if same and body.room is None:
            return {"revision":draft["revision"],"ok":True}
        if body.room is not None:
            room=" ".join(body.room.split())
            if not room: raise HTTPException(422,"Укажите кабинет")
            if not map_can_change_room(entry): raise HTTPException(422,"Нельзя заменить один кабинет для нескольких групп или учителей.")
            for kind in ("teachers","subjects"):
                cell=entry[kind]
                groups=[{**g,"room":room} for g in cell.get("groups",[])]
                entry[kind]={**cell,"rooms":[room],"raw":", ".join(cell.get("names",[])) or cell.get("raw", "")}
                if "groups" in cell: entry[kind]["groups"]=groups
        for kind in ("teachers","subjects"):
            existing=schedule_map.getcell(data,kind,body.target_day,target_raw,body.class_name) or {}
            if not same and (existing.get("names") or existing.get("raw") or existing.get("rooms")):
                raise HTTPException(409,"Ячейка занята. Сначала перенесите урок из неё.")
        shift=2 if body.class_name in (data.get("second_shift_classes") or []) else 1
        check_map_conflicts(data,body.class_name,body.target_day,shift,body.target_lesson,entry["teachers"],entry["subjects"])
        for kind in ("teachers","subjects"):
            if data.get(kind):
                cell=entry[kind] if body.room is not None else schedule_map.getcell(data,kind,body.day,body.raw,body.class_name)
                schedule_map.putcell(data,kind,body.day,body.raw,body.class_name,None)
                schedule_map.putcell(data,kind,body.target_day,target_raw,body.class_name,cell)
        events=copy.deepcopy(draft.get("move_events",[]))
        if not same:
            events.append({"type":"move","class_name":body.class_name,"source":original_entry,"target":{"day":body.target_day,"raw":target_raw}})
        updated={"base":draft["base"],"revision":draft["revision"]+1,"data":data,"move_events":events}
        state["schedule_map_draft"]=updated;_save_state()
        return {"revision":updated["revision"],"ok":True}


class MapTeacherTransfer(BaseModel):
    revision: int = Field(ge=0)
    source: str = Field(min_length=1,max_length=80)
    target: str = Field(min_length=1,max_length=80)


@app.post("/api/admin/schedule-map/transfer-teacher")
def transfer_map_teacher(body: MapTeacherTransfer, _: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        draft,stale=map_current()
        if stale or draft["revision"]!=body.revision:raise HTTPException(409,"Расписание или карта изменились. Обновите данные.")
        source=normalize_teacher_initials(body.source).casefold()
        target_name=next((x.name for x in _planner_project().teachers if x.name==body.target),None)
        if not target_name:raise HTTPException(422,"Новый учитель должен быть в справочнике конструктора.")
        target=normalize_teacher_initials(target_name).casefold()
        if source==target:raise HTTPException(422,"Выберите двух разных учителей.")
        data=copy.deepcopy(draft["data"])
        classes={c for kind in ("teachers","subjects") for c in (data.get(kind) or {}).get("classes",[])}
        affected=[]
        for cls in classes:
            for entry in schedule_map.entries(data,cls):
                names=entry["teachers"].get("names",[])
                if not any(normalize_teacher_initials(name).casefold()==source for name in names):continue
                if any(normalize_teacher_initials(name).casefold()==target for name in names):raise HTTPException(409,f"В {cls}, {entry['day']}, урок {entry['lesson']} новый учитель уже указан. Исправьте эту ячейку вручную.")
                affected.append((cls,entry))
        if not affected:raise HTTPException(422,"У выбранного учителя нет уроков в текущем черновике карты.")
        for cls,entry in affected:
            for kind in ("teachers","subjects"):
                if not data.get(kind):continue
                cell=copy.deepcopy(schedule_map.getcell(data,kind,entry["day"],entry["raw"],cls))
                if cell is None:continue
                if kind=="teachers":
                    cell["names"]=[target_name if normalize_teacher_initials(name).casefold()==source else name for name in cell.get("names",[])]
                    cell["raw"]=", ".join(cell["names"])
                if isinstance(cell.get("groups"),list):
                    for group in cell["groups"]:
                        if normalize_teacher_initials(group.get("teacher","")).casefold()==source:group["teacher"]=target_name
                schedule_map.putcell(data,kind,entry["day"],entry["raw"],cls,cell)
        for cls,old in affected:
            entry=map_entry_at(data,cls,old["day"],old["raw"])
            check_map_conflicts(data,cls,entry["day"],entry["shift"],entry["lesson"],entry["teachers"],entry["subjects"])
            period=schedule_map.period(data,entry["shift"],entry["day"],entry["lesson"])
            start,end=schedule_map.clock(period.get("start")),schedule_map.clock(period.get("end"))
            for other in schedule_map.entries(data,cls):
                if other["day"]!=entry["day"] or other["raw"]==entry["raw"] or not any(normalize_teacher_initials(n).casefold()==target for n in other["teachers"].get("names",[])):continue
                other_period=schedule_map.period(data,other["shift"],other["day"],other["lesson"])
                a,b=schedule_map.clock(other_period.get("start")),schedule_map.clock(other_period.get("end"))
                if a is None or b is None or a>=b:raise HTTPException(422,"Нельзя проверить занятость нового учителя: не хватает времени звонков.")
                if start<b and a<end:raise HTTPException(409,f"Учитель занят: {cls}, {entry['day']}, урок {other['lesson']}.")
        updated={"base":draft["base"],"revision":draft["revision"]+1,"data":data,"move_events":copy.deepcopy(draft.get("move_events",[]))}
        state["schedule_map_draft"]=updated;_save_state()
        return {"revision":updated["revision"],"transferred":len(affected)}


class MapRemove(BaseModel):
    revision: int = Field(ge=0)
    class_name: str = Field(min_length=1,max_length=80)
    day: Literal["Пн","Вт","Ср","Чт","Пт","Сб"]
    raw: str = Field(pattern=r"^\d{1,2}$")
    teacher: str = Field(min_length=1,max_length=80)


@app.post("/api/admin/schedule-map/remove")
def remove_schedule_map_lesson(body: MapRemove, _: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        draft,stale=map_current()
        if stale or body.revision!=draft["revision"]:raise HTTPException(409,"Расписание или карта изменились. Обновите данные.")
        data=copy.deepcopy(draft["data"])
        entry=next((e for e in schedule_map.entries(data,body.class_name) if e["day"]==body.day and e["raw"]==body.raw),None)
        if not entry:raise HTTPException(404,"Урок не найден")
        names=entry["teachers"].get("names",[]);groups=entry["teachers"].get("groups",[]) or entry["subjects"].get("groups",[])
        if len(names)!=1 or names[0]!=body.teacher or len(groups)>1:
            raise HTTPException(422,"В ячейке несколько учителей или групп. Чтобы не удалить чужой урок, измените её в конструкторе групп.")
        for kind in ("teachers","subjects"):
            if data.get(kind):schedule_map.putcell(data,kind,body.day,body.raw,body.class_name,None)
        events=copy.deepcopy(draft.get("move_events",[]))
        events.append({"type":"remove","class_name":body.class_name,"source":copy.deepcopy(entry)})
        updated={"base":draft["base"],"revision":draft["revision"]+1,"data":data,"move_events":events}
        state["schedule_map_draft"]=updated;_save_state();return {"revision":updated["revision"],"ok":True}


def public_dated_changes():
    fingerprint=map_fingerprint(schedule_map.snapshot(state))
    return [{k:v for k,v in entry.items() if k not in ("cells","base")} | {"stale": entry.get("base")!=fingerprint} for entry in state.get("dated_schedule_changes",[])]


def dated_projection(data, day_date, changes):
    """Снимок недельного расписания с исключениями для одного календарного дня."""
    result=copy.deepcopy(data)
    for change in changes:
        if change["source_date"]==day_date:
            for kind in ("teachers","subjects"):
                if result.get(kind): schedule_map.putcell(result,kind,change["day"],change["raw"],change["class_name"],None)
    for change in changes:
        if change.get("target_date")==day_date:
            for kind in ("teachers","subjects"):
                if result.get(kind):schedule_map.putcell(result,kind,change["target_day"],change["target_raw"],change["class_name"],copy.deepcopy(change["cells"].get(kind)))
    return result


class DatedChange(BaseModel):
    revision: int = Field(ge=0)
    class_name: str = Field(min_length=1,max_length=80)
    day: Literal["Пн","Вт","Ср","Чт","Пт","Сб"]
    raw: str = Field(pattern=r"^\d{1,2}$")
    teacher: str = Field(min_length=1,max_length=80)
    source_date: date
    target_date: date | None = None
    target_lesson: int | None = Field(default=None,ge=1,le=12)


@app.get("/api/admin/dated-schedule-changes")
def get_dated_changes(_: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        return {"revision":state.get("dated_schedule_revision",0),"changes":public_dated_changes()}


@app.post("/api/admin/dated-schedule-changes")
def create_dated_change(body: DatedChange, _: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        if state.get("schedule_map_draft"):raise HTTPException(409,"Сначала опубликуйте или отмените изменения недельной карты.")
        if body.revision!=state.get("dated_schedule_revision",0):raise HTTPException(409,"Изменения на даты обновились. Загрузите список заново.")
        source_day=body.source_date.weekday()
        if source_day>=6 or schedule_map.DAYS[source_day]!=body.day:raise HTTPException(422,"Дата не совпадает с днём выбранного урока.")
        if (body.target_date is None)!=(body.target_lesson is None):raise HTTPException(422,"Для переноса укажите дату и номер урока.")
        if body.target_date and body.target_date.weekday()>=6:raise HTTPException(422,"Перенос на воскресенье не поддерживается.")
        data=schedule_map.snapshot(state);base=map_fingerprint(data);changes=state.get("dated_schedule_changes",[])
        if any(x.get("base")!=base for x in changes):raise HTTPException(409,"Недельное расписание изменилось: проверьте и удалите устаревшие изменения на даты.")
        if len(changes)>=2000:raise HTTPException(422,"Достигнут предел изменений на даты.")
        source=body.source_date.isoformat();projected=dated_projection(data,source,changes)
        entry=next((e for e in schedule_map.entries(projected,body.class_name) if e["day"]==body.day and e["raw"]==body.raw),None)
        if not entry:raise HTTPException(404,"Урок на эту дату не найден или уже изменён.")
        names=entry["teachers"].get("names",[]);groups=entry["teachers"].get("groups",[]) or entry["subjects"].get("groups",[])
        if len(names)!=1 or names[0]!=body.teacher or len(groups)>1:raise HTTPException(422,"Урок с несколькими учителями или группами нельзя изменить отдельно без проверки структуры.")
        # Источником может быть только обычный урок, не результат другого переноса.
        if any(x.get("target_date")==source and x["class_name"]==body.class_name and x.get("target_raw")==body.raw for x in changes):raise HTTPException(409,"Сначала отмените предыдущий перенос этого урока.")
        cells={kind:copy.deepcopy(schedule_map.getcell(projected,kind,body.day,body.raw,body.class_name)) for kind in ("teachers","subjects")}
        target_date=body.target_date.isoformat() if body.target_date else None;target_day=target_raw=None
        if target_date:
            target_day=schedule_map.DAYS[body.target_date.weekday()]
            destination=dated_projection(data,target_date,changes)
            if target_date==source:
                for kind in ("teachers","subjects"):
                    if destination.get(kind):schedule_map.putcell(destination,kind,body.day,body.raw,body.class_name,None)
            target_raw=schedule_map.destination(destination,body.class_name,target_day,body.target_lesson)
            if source==target_date and body.raw==target_raw:raise HTTPException(422,"Выберите другое время или дату.")
            for kind in ("teachers","subjects"):
                existing=schedule_map.getcell(destination,kind,target_day,target_raw,body.class_name) or {}
                if existing.get("names") or existing.get("raw") or existing.get("rooms"):raise HTTPException(409,"У класса уже есть урок в это время.")
            shift=2 if body.class_name in (data.get("second_shift_classes") or []) else 1
            check_map_conflicts(destination,body.class_name,target_day,shift,body.target_lesson,entry["teachers"],entry["subjects"])
        item={"id":secrets.token_hex(16),"base":base,"class_name":body.class_name,"teacher":body.teacher,"subject":", ".join(entry["subjects"].get("names",[])),"source_date":source,"day":body.day,"raw":body.raw,"source_lesson":entry["lesson"],"target_date":target_date,"target_day":target_day,"target_lesson":body.target_lesson,"target_raw":target_raw,"cells":cells}
        state["dated_schedule_changes"]=[*changes,item];state["dated_schedule_revision"]=body.revision+1;_touch_updated_at();_save_state()
        return {"revision":body.revision+1,"changes":public_dated_changes()}


class DatedReset(BaseModel):
    revision: int = Field(ge=0)


@app.post("/api/admin/dated-schedule-changes/reset")
def reset_dated_changes(body: DatedReset, _: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        if body.revision != state.get("dated_schedule_revision",0):raise HTTPException(409,"Изменения на даты обновились. Загрузите список заново.")
        state["dated_schedule_changes"]=[];state["dated_schedule_revision"]=body.revision+1;_touch_updated_at();_save_state()
        return {"revision":body.revision+1,"changes":[]}


@app.delete("/api/admin/dated-schedule-changes/{change_id}")
def delete_dated_change(change_id: str, revision: int, _: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        if revision!=state.get("dated_schedule_revision",0):raise HTTPException(409,"Изменения на даты обновились. Загрузите список заново.")
        changes=state.get("dated_schedule_changes",[]);item=next((x for x in changes if x["id"]==change_id),None)
        if not item:raise HTTPException(404,"Изменение не найдено")
        days={item["source_date"],item.get("target_date")}-{None}
        if any(x is not item and days & {x["source_date"],x.get("target_date")} for x in changes):raise HTTPException(409,"Сначала отмените другие изменения на те же даты, чтобы не создать конфликт.")
        state["dated_schedule_changes"]=[x for x in changes if x["id"]!=change_id];state["dated_schedule_revision"]=revision+1;_touch_updated_at();_save_state();return {"revision":revision+1,"changes":public_dated_changes()}


class MapEdit(BaseModel):
    revision: int = Field(ge=0)
    class_name: str = Field(min_length=1,max_length=80)
    day: Literal["Пн","Вт","Ср","Чт","Пт","Сб"]
    raw: str = Field(pattern=r"^\d{1,2}$")
    teachers: list[str] = Field(max_length=10)
    subjects: list[str] = Field(max_length=10)
    rooms: list[str] = Field(max_length=10)


@app.post("/api/admin/schedule-map/edit")
def edit_schedule_map(body: MapEdit, _: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        draft,stale=map_current()
        if stale or body.revision!=draft["revision"]:raise HTTPException(409,"Расписание или карта изменились. Обновите данные.")
        data=copy.deepcopy(draft["data"])
        entry=next((e for e in schedule_map.entries(data,body.class_name) if e["day"]==body.day and e["raw"]==body.raw),None)
        if not entry:raise HTTPException(404,"Урок не найден")
        if any(entry[k].get("groups") for k in ("teachers","subjects")):
            raise HTTPException(422,"Урок содержит данные групп. Их можно изменить в черновике конструктора.")
        def clean(items):
            result=[" ".join(x.split()) for x in items]
            if any(not x or len(x)>80 for x in result):raise HTTPException(422,"Проверьте названия: они не должны быть пустыми или длиннее 80 символов")
            return result
        teachers,subjects,rooms=clean(body.teachers),clean(body.subjects),clean(body.rooms)
        if not teachers and not subjects:raise HTTPException(422,"Укажите учителя или предмет")
        if (teachers and not data.get("teachers")) or (subjects and not data.get("subjects")):
            raise HTTPException(422,"Отсутствует соответствующий файл расписания")
        t={**entry["teachers"],"names":teachers,"raw":", ".join(teachers),"rooms":rooms}
        s={**entry["subjects"],"names":subjects,"raw":", ".join(subjects),"rooms":rooms}
        if teachers!=entry["teachers"].get("names",[]) or rooms!=entry["teachers"].get("rooms",[]):
            check_map_conflicts(data,body.class_name,body.day,entry["shift"],entry["lesson"],t,s)
        for kind,cell in (("teachers",t),("subjects",s)):
            if data.get(kind):schedule_map.putcell(data,kind,body.day,body.raw,body.class_name,cell)
        updated={"base":draft["base"],"revision":draft["revision"]+1,"data":data,"move_events":copy.deepcopy(draft.get("move_events",[]))}
        state["schedule_map_draft"]=updated;_save_state();return {"revision":updated["revision"],"ok":True}


class MapPublish(BaseModel):
    revision: int = Field(ge=0)


@app.post("/api/admin/schedule-map/reset")
def reset_schedule_map(body: MapPublish, _: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        draft,_=map_current()
        if body.revision != draft["revision"]:raise HTTPException(409,"Карта изменена в другом окне. Обновите данные.")
        state["schedule_map_draft"]=None;_save_state()
        return {"ok":True}


@app.post("/api/admin/schedule-map/publish")
def publish_schedule_map(body: MapPublish, _: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        draft,stale=map_current()
        if stale or draft["revision"]!=body.revision: raise HTTPException(409,"Расписание или карта изменились. Обновите данные.")
        if not state.get("schedule_map_draft"): raise HTTPException(422,"Нет изменений для публикации")
        notices=build_weekly_move_notices(draft,time.time())
        for kind in ("teachers","subjects"):
            state[kind]=draft["data"][kind]
        state["weekly_move_notices"]=notices
        state["schedule_map_draft"]=None;_touch_updated_at();_save_state()
        return {"ok":True}


class PlannerMove(BaseModel):
    revision: int = Field(ge=0)
    index: int = Field(ge=0)
    day: Literal["Пн", "Вт", "Ср", "Чт", "Пт", "Сб"]
    lesson: int = Field(ge=1, le=12)


@app.post("/api/admin/planner/move")
def planner_move(body: PlannerMove, _: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        project = _planner_project()
        if body.revision != project.revision:
            raise HTTPException(409, "Черновик изменён в другом окне. Обновите конструктор.")
        if body.index >= len(project.placements):
            raise HTTPException(404, "Урок не найден")
        item = project.placements[body.index]
        if item.day == body.day and item.lesson == body.lesson:
            return {"project":project.model_dump(), "issues":planner.issues(project,state.get("bell_schedule"),complete=True)}
        previous = Counter(planner.issues(project, state.get("bell_schedule")))
        candidate = project.model_copy(deep=True)
        candidate.placements[body.index].day = body.day
        candidate.placements[body.index].lesson = body.lesson
        new = Counter(planner.issues(candidate, state.get("bell_schedule"))) - previous
        if new:
            raise HTTPException(422, "Перенос невозможен: " + next(iter(new)))
        candidate.revision += 1
        state["planner"] = candidate.model_dump()
        _save_state()
        return {"project":candidate.model_dump(), "issues":planner.issues(candidate,state.get("bell_schedule"),complete=True)}


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
        return {"project": generated.model_dump(), "issues": planner.issues(generated, state.get("bell_schedule"), complete=True), "teacher_gaps": planner.teacher_gap_summary(generated, state.get("bell_schedule"))}


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


@app.get("/api/admin/bell-schedule/editor")
def get_bell_editor(_: None = Depends(require_admin)) -> dict:
    with _bell_lock:
        bell = state.get("bell_schedule") or {}
        return {"shifts": bell.get("shifts", {"1": {}, "2": {}}), "revision": bell_revision()}


@app.put("/api/admin/bell-schedule/editor")
def save_bell_editor(body: BellEdit, _: None = Depends(require_admin)) -> dict:
    shifts = {"1": {}, "2": {}}
    for item in body.entries:
        if item.start >= item.end:
            raise HTTPException(422, f"{item.day}, {item.shift}-я смена, урок {item.lesson}: окончание должно быть позже начала")
        lessons = shifts[str(item.shift)].setdefault(item.day, {})
        if str(item.lesson) in lessons:
            raise HTTPException(422, f"{item.day}, {item.shift}-я смена: урок {item.lesson} указан дважды")
        lessons[str(item.lesson)] = {"start": item.start, "end": item.end}
    for shift, days in shifts.items():
        for day, lessons in days.items():
            periods = sorted(lessons.items(), key=lambda item: item[1]["start"])
            for previous, current in zip(periods, periods[1:]):
                if current[1]["start"] < previous[1]["end"]:
                    raise HTTPException(422, f"{day}, {shift}-я смена: уроки {previous[0]} и {current[0]} пересекаются")
    with _bell_lock:
        if body.revision != bell_revision():
            raise HTTPException(409, "Расписание звонков изменилось. Загрузите его заново перед сохранением.")
        state["bell_schedule"] = {"filename": "Изменено вручную", "shifts": shifts}
        _touch_updated_at()
        _save_state()
        return {"ok": True, "revision": bell_revision()}


@app.get("/api/schedule/bell-schedule.csv")
def download_bell_schedule() -> Response:
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


@app.get("/api/admin/bell-schedule.csv")
def admin_download_bell_schedule(_: None = Depends(require_admin)) -> Response:
    return download_bell_schedule()


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
    with _bell_lock:
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
        with _bell_lock:
            state["bell_schedule"] = None
            _touch_updated_at()
            _save_state()
        return {"ok": True, "updated_at": state["updated_at"]}
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
