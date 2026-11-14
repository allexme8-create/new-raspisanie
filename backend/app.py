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
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import requests
from fastapi import Cookie, Depends, FastAPI, File, Header, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import github_backup
import planner
import schedule_map
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
    "schedule_map_draft": None,
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
        for key in ("teachers", "subjects", "bell_schedule", "second_shift_classes", "updated_at", "planner", "planner_class_imported", "planner_teachers_imported", "planner_initials_normalized", "planner_subjects_imported", "planner_rooms_imported", "planner_groups_imported", "schedule_map_draft"):
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
        project.teachers.append(planner.Teacher(name=name))
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
        catalog.append(planner.Named(name=name))
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


def check_map_conflicts(data, class_name, day, shift, lesson, teacher_cell, subject_cell):
    p=schedule_map.period(data,shift,day,lesson)
    start,end=schedule_map.clock(p.get("start")),schedule_map.clock(p.get("end"))
    if start is None or end is None or start>=end:
        raise HTTPException(422,"Для выбранного дня и урока нет времени звонков.")
    names={normalize_teacher_initials(x).casefold() for x in teacher_cell.get("names",[]) if x and x not in {"Классный час","СФУ","Экскурсия"}}
    rooms={" ".join(x.split()).casefold() for cell in (teacher_cell,subject_cell) for x in cell.get("rooms",[]) if x}
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


@app.get("/api/admin/schedule-map")
def read_schedule_map(class_name: str = "", _: None = Depends(require_admin)) -> dict:
    with _planner_lock:
        draft,stale=map_current();data=draft["data"]
        classes=list(dict.fromkeys(c for kind in ("teachers","subjects") for c in (data.get(kind) or {}).get("classes",[])))
        if class_name and class_name not in classes: raise HTTPException(404,"Класс не найден")
        return {"revision":draft["revision"],"stale":stale,"classes":classes,"entries":schedule_map.entries(data,class_name) if class_name else [],"has_changes":bool(state.get("schedule_map_draft"))}


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
        target_raw=schedule_map.destination(data,body.class_name,body.target_day,body.target_lesson)
        if body.day==body.target_day and body.raw==target_raw:
            return {"revision":draft["revision"],"ok":True}
        for kind in ("teachers","subjects"):
            existing=schedule_map.getcell(data,kind,body.target_day,target_raw,body.class_name) or {}
            if existing.get("names") or existing.get("raw") or existing.get("rooms"):
                raise HTTPException(409,"Ячейка занята. Сначала перенесите урок из неё.")
        shift=2 if body.class_name in (data.get("second_shift_classes") or []) else 1
        check_map_conflicts(data,body.class_name,body.target_day,shift,body.target_lesson,entry["teachers"],entry["subjects"])
        for kind in ("teachers","subjects"):
            if data.get(kind):
                cell=schedule_map.getcell(data,kind,body.day,body.raw,body.class_name)
                schedule_map.putcell(data,kind,body.day,body.raw,body.class_name,None)
                schedule_map.putcell(data,kind,body.target_day,target_raw,body.class_name,cell)
        updated={"base":draft["base"],"revision":draft["revision"]+1,"data":data}
        state["schedule_map_draft"]=updated;_save_state()
        return {"revision":updated["revision"],"ok":True}


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
        updated={"base":draft["base"],"revision":draft["revision"]+1,"data":data}
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
        for kind in ("teachers","subjects"):
            state[kind]=draft["data"][kind]
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
