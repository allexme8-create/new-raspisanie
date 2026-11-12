"""Private staff accounts and task workflow, stored outside the public schedule backup."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import tempfile
import time
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, EmailStr, Field, field_validator

SESSION_TTL = 12 * 60 * 60
SCHOOL_TIMEZONE = os.environ.get("SCHOOL_TIMEZONE", "Asia/Krasnoyarsk")


def school_today() -> date:
    return datetime.now(ZoneInfo(SCHOOL_TIMEZONE)).date()


def duty_quarter(today: date) -> tuple[date, date, int, bool]:
    year = today.year
    periods = [(date(year, 1, 10), date(year, 3, 31), 3),
               (date(year, 4, 1), date(year, 5, 31), 4),
               (date(year, 9, 1), date(year, 10, 31), 1),
               (date(year, 11, 1), date(year, 12, 31), 2),
               (date(year + 1, 1, 10), date(year + 1, 3, 31), 3)]
    for start, end, quarter in periods:
        if today <= end:
            return start, end, quarter, start <= today
    raise RuntimeError("Не удалось определить четверть")


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    result = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return f"{salt.hex()}:{result.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        salt, _ = stored.split(":", 1)
        return hmac.compare_digest(hash_password(password, bytes.fromhex(salt)), stored)
    except (ValueError, TypeError):
        return False


class NewUser(BaseModel):
    email: EmailStr
    role: Literal["director", "associate", "teacher"]
    position: str = Field(default="", max_length=200)
    full_name: str = Field(default="", max_length=200)

    @field_validator("full_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("position")
    @classmethod
    def clean_position(cls, value: str) -> str:
        return " ".join(value.split())


class Login(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    role: Literal["director", "associate", "teacher"]


class PasswordChange(BaseModel):
    password: str = Field(min_length=12, max_length=256)


class ProfileUpdate(BaseModel):
    full_name: str = Field(max_length=200)
    position: str | None = Field(default=None, max_length=200)

    @field_validator("position")
    @classmethod
    def clean_position(cls, value: str | None) -> str | None:
        return " ".join(value.split()) if value is not None else None

    @field_validator("full_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Укажите ФИО")
        return value


class ProjectCreate(BaseModel):
    title: str = Field(max_length=200)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Укажите название проекта")
        return value


class TaskCreate(BaseModel):
    assignee_id: str
    project_id: str | None = None
    description: str = Field(min_length=1, max_length=5000)
    deadline: datetime

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Описание не может быть пустым")
        return value

    @field_validator("deadline")
    @classmethod
    def deadline_has_zone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Укажите срок с часовым поясом")
        return value.astimezone(timezone.utc)


class DutyBooking(BaseModel):
    day: date
    shift: Literal[1, 2] | None = None
    class_name: str = Field(default="", max_length=40)

    @field_validator("class_name")
    @classmethod
    def clean_class(cls, value: str) -> str:
        return " ".join(value.split())


class Complete(BaseModel):
    completed: bool
    cycle: int = Field(default=0, ge=0)
    expected_completed_at: str | None = Field(default=None, max_length=64)


class ReworkApproval(BaseModel):
    expected_completed_at: str = Field(min_length=1, max_length=64)


class Rework(BaseModel):
    comment: str = Field(max_length=2000)
    deadline: datetime
    expected_completed_at: str = Field(min_length=1, max_length=64)

    @field_validator("comment")
    @classmethod
    def clean_comment(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Укажите причину доработки")
        return value

    @field_validator("deadline")
    @classmethod
    def deadline_has_zone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Укажите срок с часовым поясом")
        return value.astimezone(timezone.utc)


class TaskProgress(BaseModel):
    partial: bool
    reason: str = Field(default="", max_length=2000)

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        return value.strip()


class NotificationRead(BaseModel):
    through_id: int = Field(ge=1)


class CollaboratorAdd(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)


class TaskComment(BaseModel):
    text: str = Field(max_length=2000)

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Комментарий не может быть пустым")
        return value


class Store:
    def __init__(self, path: Path):
        self.path = path

    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def init(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    role TEXT NOT NULL CHECK (role IN ('director','associate','teacher')),
                    password_hash TEXT NOT NULL, must_change INTEGER NOT NULL DEFAULT 1,
                    active INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, director_id TEXT NOT NULL REFERENCES users(id),
                    assignee_id TEXT NOT NULL REFERENCES users(id), description TEXT NOT NULL,
                    deadline TEXT NOT NULL, created_at TEXT NOT NULL, completed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS login_attempts (
                    key TEXT PRIMARY KEY, failures INTEGER NOT NULL, blocked_until INTEGER NOT NULL
                );
            ''')
            # SQLite cannot alter a CHECK constraint. Rebuild users without renaming it,
            # preserving child-table references, within a single transaction.
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("BEGIN IMMEDIATE")
            schema = db.execute("SELECT sql FROM sqlite_master WHERE name='users'").fetchone()[0]
            if "'teacher'" not in schema:
                db.execute("""CREATE TABLE users_new (
                    id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    role TEXT NOT NULL CHECK (role IN ('director','associate','teacher')),
                    password_hash TEXT NOT NULL, must_change INTEGER NOT NULL DEFAULT 1,
                    active INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
                    password_ciphertext TEXT, full_name TEXT NOT NULL DEFAULT '', position TEXT NOT NULL DEFAULT '')""")
                old_columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
                columns_to_copy = [c for c in ("id", "email", "role", "password_hash", "must_change", "active", "created_at", "password_ciphertext", "full_name", "position") if c in old_columns]
                names = ",".join(columns_to_copy)
                db.execute(f"INSERT INTO users_new ({names}) SELECT {names} FROM users")
                db.execute("DROP TABLE users")
                db.execute("ALTER TABLE users_new RENAME TO users")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
            if "password_ciphertext" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN password_ciphertext TEXT")
            if "full_name" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN full_name TEXT NOT NULL DEFAULT ''")
            if "position" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN position TEXT NOT NULL DEFAULT ''")
            db.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, title TEXT NOT NULL, owner_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL)")
            project_columns = {row["name"] for row in db.execute("PRAGMA table_info(projects)")}
            if "finished_at" not in project_columns:
                db.execute("ALTER TABLE projects ADD COLUMN finished_at TEXT")
            task_columns = {row["name"] for row in db.execute("PRAGMA table_info(tasks)")}
            if "project_id" not in task_columns:
                db.execute("ALTER TABLE tasks ADD COLUMN project_id TEXT REFERENCES projects(id)")
            if "partial" not in task_columns:
                db.execute("ALTER TABLE tasks ADD COLUMN partial INTEGER NOT NULL DEFAULT 0")
            if "failure_reason" not in task_columns:
                db.execute("ALTER TABLE tasks ADD COLUMN failure_reason TEXT NOT NULL DEFAULT ''")
            if "rework" not in task_columns:
                db.execute("ALTER TABLE tasks ADD COLUMN rework INTEGER NOT NULL DEFAULT 0")
            if "cycle" not in task_columns:
                db.execute("ALTER TABLE tasks ADD COLUMN cycle INTEGER NOT NULL DEFAULT 0")
            if "approved_at" not in task_columns:
                db.execute("ALTER TABLE tasks ADD COLUMN approved_at TEXT")
            db.execute("CREATE TABLE IF NOT EXISTS task_hidden (task_id TEXT NOT NULL REFERENCES tasks(id), user_id TEXT NOT NULL REFERENCES users(id), hidden_at TEXT NOT NULL, PRIMARY KEY(task_id,user_id))")
            db.execute("CREATE TABLE IF NOT EXISTS task_comments (id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), author_id TEXT NOT NULL REFERENCES users(id), text TEXT NOT NULL, created_at TEXT NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS task_comments_task ON task_comments(task_id, created_at, id)")
            db.execute("CREATE TABLE IF NOT EXISTS task_events (id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), author_id TEXT NOT NULL REFERENCES users(id), text TEXT NOT NULL, created_at TEXT NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS task_events_task ON task_events(task_id,created_at,id)")
            db.execute("CREATE TABLE IF NOT EXISTS task_collaborators (task_id TEXT NOT NULL REFERENCES tasks(id), user_id TEXT NOT NULL REFERENCES users(id), added_at TEXT NOT NULL, PRIMARY KEY (task_id, user_id))")
            db.execute("CREATE INDEX IF NOT EXISTS task_collaborators_user ON task_collaborators(user_id, task_id)")
            db.execute("CREATE TABLE IF NOT EXISTS task_notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES tasks(id), recipient_id TEXT NOT NULL REFERENCES users(id), actor_id TEXT NOT NULL REFERENCES users(id), kind TEXT NOT NULL, created_at TEXT NOT NULL, read_at TEXT)")
            db.execute("CREATE INDEX IF NOT EXISTS task_notifications_unread ON task_notifications(recipient_id,read_at,task_id,id)")
            db.execute("""CREATE TABLE IF NOT EXISTS duty_assignments (
                day TEXT NOT NULL, slot INTEGER NOT NULL CHECK(slot IN (0,1,2)),
                user_id TEXT NOT NULL REFERENCES users(id), class_name TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(day,slot), UNIQUE(day,user_id))""")
            # Почтовые настройки и коды больше не используются.
            for name in ("mail_oauth", "mail_oauth_pending", "password_resets", "reset_throttle", "reset_ip_throttle"):
                db.execute(f"DROP TABLE IF EXISTS {name}")
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='settings'").fetchone():
                db.execute("DELETE FROM settings WHERE key='smtp_sender'")
        self.path.chmod(0o600)

    @property
    def key_path(self) -> Path:
        return self.path.with_suffix(".key")

    def cipher(self) -> Fernet:
        try:
            if not self.key_path.exists():
                with self.connect() as db:
                    if db.execute("SELECT 1 FROM users WHERE password_ciphertext IS NOT NULL LIMIT 1").fetchone():
                        raise RuntimeError("Ключ шифрования потерян. Восстановите файл staff.key из резервной копии.")
                # Атомарная публикация исключает чтение частично записанного ключа.
                fd, temp = tempfile.mkstemp(prefix=".staff-key-", dir=self.path.parent)
                try:
                    os.fchmod(fd, 0o600)
                    with os.fdopen(fd, "wb") as output:
                        output.write(Fernet.generate_key())
                        output.flush()
                        os.fsync(output.fileno())
                    try:
                        os.link(temp, self.key_path)
                    except FileExistsError:
                        pass
                finally:
                    os.unlink(temp)
            cipher = Fernet(self.key_path.read_bytes())
            with self.connect() as db:
                sample = db.execute("SELECT password_ciphertext FROM users WHERE password_ciphertext IS NOT NULL LIMIT 1").fetchone()
            if sample:
                cipher.decrypt(sample["password_ciphertext"].encode("ascii"))
            return cipher
        except RuntimeError:
            raise
        except (OSError, ValueError, InvalidToken, UnicodeError) as exc:
            raise RuntimeError("Не удалось открыть ключ шифрования паролей. Проверьте хранение данных сервера.") from exc

    def encrypt_password(self, password: str) -> str:
        return self.cipher().encrypt(password.encode("utf-8")).decode("ascii")

    def decrypt_password(self, value: str) -> str:
        try:
            return self.cipher().decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, UnicodeError) as exc:
            raise RuntimeError("Не удалось расшифровать пароль. Проверьте ключ шифрования.") from exc


def public_user(user) -> dict:
    return {key: user[key] for key in ("id", "email", "role", "full_name", "position")}


def visible_task_events(events) -> list[dict]:
    """Hide accidental completion and its cancellation from the task history.

    Keep the stored events for audit, and never remove completions from an earlier
    rework cycle when a legacy completion has no corresponding event.
    """
    visible = []
    last_completion = None
    for row in events:
        event = dict(row)
        text = event["text"]
        if text.startswith("Исполнитель снял отметку выполнения ("):
            if last_completion is not None:
                visible[last_completion] = None
            last_completion = None
        else:
            visible.append(event)
            if text == "Задача выполнена":
                last_completion = len(visible) - 1
            elif text.startswith("Возвращено на доработку.") or text == "Инициатор подтвердил: выполнено полностью":
                last_completion = None
    return [event for event in visible if event is not None]


def task_json(row, current: datetime | None = None) -> dict:
    due = datetime.fromisoformat(row["deadline"])
    completed = datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None
    current = current or now()
    status = ("completed_on_time" if completed <= due else "completed_late") if completed else ("overdue" if current > due else "pending")
    return {key: row[key] for key in ("id", "description", "deadline", "created_at", "completed_at", "assignee_id", "assignee_email", "director_email", "assignee_name", "director_name", "project_id", "director_id", "assignee_position", "director_position", "failure_reason", "approved_at")} | {"status": status, "partial": bool(row["partial"]), "rework": bool(row["rework"]), "cycle": row["cycle"]}


TASK_SELECT = '''SELECT tasks.*, CASE WHEN assignee.active=1 THEN assignee.email ELSE 'Удалённый пользователь' END AS assignee_email,
                 CASE WHEN director.active=1 THEN director.email ELSE 'Удалённый пользователь' END AS director_email,
                 CASE WHEN assignee.active=1 THEN assignee.full_name ELSE 'Удалённый пользователь' END AS assignee_name,
                 CASE WHEN director.active=1 THEN director.full_name ELSE 'Удалённый пользователь' END AS director_name,
                 CASE WHEN assignee.active=1 THEN COALESCE(NULLIF(assignee.position,''), CASE assignee.role WHEN 'teacher' THEN 'Учитель' WHEN 'associate' THEN 'Заместитель директора' ELSE 'Директор' END) ELSE '' END AS assignee_position,
                 CASE WHEN director.active=1 THEN COALESCE(NULLIF(director.position,''), CASE director.role WHEN 'teacher' THEN 'Учитель' WHEN 'associate' THEN 'Заместитель директора' ELSE 'Директор' END) ELSE '' END AS director_position
                 FROM tasks JOIN users assignee ON assignee.id=tasks.assignee_id
                 JOIN users director ON director.id=tasks.director_id'''


def make_router(store: Store, require_admin) -> APIRouter:
    router = APIRouter()
    store.init()
    # A fixed dummy hash makes unknown-account login perform the same expensive work.
    dummy_hash = hash_password(secrets.token_urlsafe(24))

    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def require_staff(authorization: str = Header(default=""), x_staff_token: str = Header(default="", alias="X-Staff-Token")) -> dict:
        token = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else x_staff_token.strip()
        if not token or len(token) > 256:
            raise HTTPException(401, "Требуется вход")
        with store.connect() as db:
            row = db.execute('''SELECT users.*, sessions.token_hash FROM sessions JOIN users ON users.id=sessions.user_id
                                WHERE sessions.token_hash=? AND sessions.expires>? AND users.active=1''', (token_hash(token), int(time.time()))).fetchone()
        if not row:
            raise HTTPException(401, "Сессия истекла — войдите заново")
        return dict(row)

    def ready_user(user: dict = Depends(require_staff)) -> dict:
        if user["must_change"]:
            raise HTTPException(403, "Сначала смените временный пароль")
        return user

    def director(user: dict = Depends(ready_user)) -> dict:
        if user["role"] != "director":
            raise HTTPException(403, "Доступ только для директора")
        return user

    def explicit_admin(_: None = Depends(require_admin), authorization: str = Header(default=""), x_admin_token: str = Header(default="", alias="X-Admin-Token")) -> None:
        # Не разрешаем доступ только по cookie: это предотвращает межсайтовые формы.
        if not (authorization.startswith("Bearer ") and authorization[7:].strip()) and not x_admin_token.strip():
            raise HTTPException(401, "Для управления пользователями войдите в админку заново")

    @router.get("/api/admin/users")
    def list_users(_: None = Depends(explicit_admin)):
        with store.connect() as db:
            rows = db.execute("SELECT id,email,role,full_name,position FROM users WHERE active=1 ORDER BY email").fetchall()
        return {"users": [public_user(row) for row in rows]}

    @router.post("/api/admin/users", status_code=201)
    def create_user(body: NewUser, _: None = Depends(explicit_admin)):
        email = str(body.email).strip().lower()
        uid, password = secrets.token_hex(16), secrets.token_urlsafe(18)
        try:
            encrypted = store.encrypt_password(password)
            with store.connect() as db:
                db.execute("INSERT INTO users (id,email,role,password_hash,password_ciphertext,must_change,active,created_at,position,full_name) VALUES (?,?,?,?,?,1,1,?,?,?)", (uid, email, body.role, hash_password(password), encrypted, iso(now()), body.position, body.full_name))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Пользователь с таким e-mail уже существует")
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        return {"user": {"id": uid, "email": email, "role": body.role, "full_name": body.full_name, "position": body.position}, "password": password}

    @router.post("/api/admin/users/{user_id}/password")
    def reveal_password(user_id: str, _: None = Depends(explicit_admin)):
        with store.connect() as db:
            row = db.execute("SELECT password_ciphertext FROM users WHERE id=? AND active=1", (user_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Пользователь не найден")
        if not row["password_ciphertext"]:
            raise HTTPException(409, "Старый пароль нельзя восстановить. Обновите пароль пользователя.")
        try:
            return {"password": store.decrypt_password(row["password_ciphertext"])}
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    @router.post("/api/admin/users/{user_id}/password/reset")
    def reset_password(user_id: str, _: None = Depends(explicit_admin)):
        password = secrets.token_urlsafe(18)
        try:
            encrypted = store.encrypt_password(password)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT email FROM users WHERE id=? AND active=1", (user_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Пользователь не найден")
            db.execute("UPDATE users SET password_hash=?,password_ciphertext=?,must_change=1 WHERE id=?", (hash_password(password), encrypted, user_id))
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM login_attempts WHERE key=?", (hashlib.sha256(row["email"].encode()).hexdigest(),))
        return {"password": password}

    @router.delete("/api/admin/users/{user_id}")
    def delete_user(user_id: str, _: None = Depends(explicit_admin)):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT email FROM users WHERE id=? AND active=1", (user_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Пользователь не найден")
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM login_attempts WHERE key=?", (hashlib.sha256(row["email"].encode()).hexdigest(),))
            db.execute("DELETE FROM duty_assignments WHERE user_id=? AND day>=?", (user_id,school_today().isoformat()))
            db.execute("UPDATE users SET active=0,email=?,password_hash='',password_ciphertext=NULL,full_name='',position='',must_change=1 WHERE id=?", (f"__deleted__:{user_id}", user_id))
        return {"ok": True}

    @router.post("/api/staff/login")
    def login(body: Login):
        email = str(body.email).strip().lower()
        key = hashlib.sha256(email.encode()).hexdigest()
        current = int(time.time())
        with store.connect() as db:
            attempt = db.execute("SELECT * FROM login_attempts WHERE key=?", (key,)).fetchone()
            if attempt and attempt["blocked_until"] > current:
                raise HTTPException(429, "Слишком много попыток. Повторите через 15 минут.")
            row = db.execute("SELECT * FROM users WHERE email=? AND active=1", (email,)).fetchone()
            valid = check_password(body.password, row["password_hash"] if row else dummy_hash)
            if not valid or not row or row["role"] != body.role:
                failures = (attempt["failures"] if attempt and attempt["blocked_until"] == 0 else 0) + 1
                db.execute("INSERT INTO login_attempts VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET failures=excluded.failures, blocked_until=excluded.blocked_until", (key, failures, current + 900 if failures >= 5 else 0))
                db.commit()
                raise HTTPException(401, "Неверный логин, пароль или раздел входа")
            db.execute("DELETE FROM login_attempts WHERE key=?", (key,))
            db.execute("DELETE FROM sessions WHERE expires<=?", (current,))
            token = secrets.token_urlsafe(32)
            db.execute("INSERT INTO sessions VALUES (?,?,?)", (token_hash(token), row["id"], current + SESSION_TTL))
        return {"token": token, "user": public_user(row), "must_change": bool(row["must_change"])}

    @router.get("/api/staff/me")
    def me(user: dict = Depends(require_staff)):
        return {"user": public_user(user), "must_change": bool(user["must_change"])}

    @router.put("/api/staff/profile")
    def update_profile(body: ProfileUpdate, user: dict = Depends(ready_user)):
        with store.connect() as db:
            updated = db.execute("UPDATE users SET full_name=?,position=COALESCE(?,position) WHERE id=? AND active=1 AND EXISTS (SELECT 1 FROM sessions WHERE user_id=? AND token_hash=? AND expires>?)", (body.full_name, body.position, user["id"], user["id"], user["token_hash"], int(time.time())))
            if not updated.rowcount:
                raise HTTPException(401, "Сессия истекла — войдите заново")
            row = db.execute("SELECT id,email,role,full_name,position FROM users WHERE id=?", (user["id"],)).fetchone()
        return {"user": public_user(row)}

    @router.post("/api/staff/logout")
    def logout(user: dict = Depends(require_staff)):
        with store.connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (user["token_hash"],))
        return {"ok": True}

    @router.post("/api/staff/password")
    def change_password(body: PasswordChange, user: dict = Depends(require_staff)):
        if check_password(body.password, user["password_hash"]):
            raise HTTPException(422, "Новый пароль должен отличаться от текущего")
        try:
            encrypted = store.encrypt_password(body.password)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            updated = db.execute("UPDATE users SET password_hash=?,password_ciphertext=?,must_change=0 WHERE id=? AND active=1 AND password_hash=? AND EXISTS (SELECT 1 FROM sessions WHERE user_id=? AND token_hash=? AND expires>?)", (hash_password(body.password), encrypted, user["id"], user["password_hash"], user["id"], user["token_hash"], int(time.time())))
            if not updated.rowcount:
                raise HTTPException(401, "Сессия истекла — войдите заново")
            db.execute("DELETE FROM sessions WHERE user_id=? AND token_hash<>?", (user["id"], user["token_hash"]))
        return {"ok": True}

    def duty_rows(db, start: date, end: date, viewer_id: str | None = None):
        rows = db.execute("""SELECT duty_assignments.day,duty_assignments.slot,duty_assignments.user_id,duty_assignments.class_name,users.active,
            CASE WHEN users.active=1 THEN users.full_name ELSE 'Удалённый пользователь' END AS full_name,
            CASE WHEN users.active=1 THEN COALESCE(NULLIF(users.position,''),CASE users.role WHEN 'teacher' THEN 'Учитель' ELSE 'Заместитель директора' END) ELSE '' END AS position
            FROM duty_assignments JOIN users ON users.id=duty_assignments.user_id
            WHERE duty_assignments.day BETWEEN ? AND ? ORDER BY duty_assignments.day,duty_assignments.slot""", (start.isoformat(), end.isoformat())).fetchall()
        return [{"day": row["day"], "slot": row["slot"], "class_name": row["class_name"] if row["active"] else "", "full_name": row["full_name"], "position": row["position"], "mine": bool(viewer_id and row["user_id"] == viewer_id)} for row in rows]

    def duty_user(user: dict = Depends(ready_user)) -> dict:
        if user["role"] not in ("teacher", "associate"):
            raise HTTPException(403, "Дежурство доступно учителям и заместителям")
        return user

    @router.get("/api/staff/duty")
    def duty_calendar(user: dict = Depends(duty_user)):
        today = school_today()
        start, end, quarter, active = duty_quarter(today)
        with store.connect() as db:
            entries = duty_rows(db, start, end, user["id"])
        return {"today": today.isoformat(), "start": start.isoformat(), "end": end.isoformat(), "quarter": quarter, "active": active, "timezone": SCHOOL_TIMEZONE, "entries": entries}

    @router.post("/api/staff/duty", status_code=201)
    def book_duty(body: DutyBooking, user: dict = Depends(duty_user)):
        today = school_today()
        start, end, _, active = duty_quarter(today)
        if not active or not start <= body.day <= end or body.day < today:
            raise HTTPException(422, "Выберите сегодняшнюю или будущую дату текущей четверти")
        if not user["full_name"]:
            raise HTTPException(422, "Сначала укажите ФИО в профиле")
        if user["role"] == "teacher":
            if body.shift is None or not body.class_name:
                raise HTTPException(422, "Укажите смену и класс")
            slot, class_name = body.shift, body.class_name
        else:
            if body.shift is not None or body.class_name:
                raise HTTPException(422, "Заместитель выбирает дежурство администратора")
            slot, class_name = 0, ""
        try:
            with store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                # Recheck session and user inside the transaction before reserving a slot.
                if not db.execute("SELECT 1 FROM sessions JOIN users ON users.id=sessions.user_id WHERE sessions.token_hash=? AND sessions.expires>? AND users.active=1 AND users.id=?", (user["token_hash"], int(time.time()), user["id"])).fetchone():
                    raise HTTPException(401, "Сессия истекла — войдите заново")
                db.execute("INSERT INTO duty_assignments (day,slot,user_id,class_name) VALUES (?,?,?,?)", (body.day.isoformat(),slot,user["id"],class_name))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Место занято или вы уже записаны на эту дату. Обновите карту.")
        return {"ok": True}

    @router.delete("/api/staff/duty/{day}/{slot}")
    def cancel_duty(day: date, slot: int, user: dict = Depends(duty_user)):
        if slot not in (0,1,2) or day < school_today():
            raise HTTPException(422, "Нельзя отменить прошедшее дежурство")
        with store.connect() as db:
            deleted = db.execute("DELETE FROM duty_assignments WHERE day=? AND slot=? AND user_id=?", (day.isoformat(),slot,user["id"]))
            if not deleted.rowcount:
                raise HTTPException(404, "Дежурство не найдено")
        return {"ok": True}

    @router.get("/api/duties/today")
    def public_today_duties():
        today = school_today()
        with store.connect() as db:
            entries = duty_rows(db,today,today)
        for entry in entries:
            entry.pop("mine",None)
        return {"today":today.isoformat(), "timezone":SCHOOL_TIMEZONE,"entries":entries}

    @router.get("/api/staff/associates")
    def associates(_: dict = Depends(director)):
        with store.connect() as db:
            rows = db.execute("SELECT id,email,role,full_name,position FROM users WHERE role='associate' AND active=1 ORDER BY email").fetchall()
        return {"users": [public_user(row) for row in rows]}

    def manager(user: dict = Depends(ready_user)) -> dict:
        if user["role"] not in ("director", "associate"):
            raise HTTPException(403, "Доступ только для руководства")
        return user

    @router.get("/api/staff/deadline-stats")
    def deadline_stats(user: dict = Depends(manager)):
        # Statistics follow the primary assignee and the current agreed deadline;
        # hidden tasks and project tasks still count for their initiator.
        with store.connect() as db:
            rows = db.execute("""SELECT tasks.deadline,tasks.completed_at,users.id,users.active,users.role,
                users.full_name,users.position FROM tasks JOIN users ON users.id=tasks.assignee_id
                WHERE tasks.director_id=? ORDER BY users.full_name,users.id""", (user["id"],)).fetchall()
        current = now()
        people = {}
        for row in rows:
            person = people.setdefault(row["id"], {
                "id": row["id"],
                "full_name": row["full_name"] if row["active"] else "Удалённый пользователь",
                "position": row["position"] if row["active"] else "",
                "role": row["role"] if row["active"] else "",
                "completed_on_time": 0,
                "overdue": 0,
            })
            deadline = datetime.fromisoformat(row["deadline"])
            if row["completed_at"]:
                completed = datetime.fromisoformat(row["completed_at"])
                person["completed_on_time" if completed <= deadline else "overdue"] += 1
            elif current > deadline:
                person["overdue"] += 1
        return {"users": list(people.values())}

    @router.get("/api/staff/assignees")
    def assignees(user: dict = Depends(manager)):
        roles = ("associate", "teacher") if user["role"] == "director" else ("teacher",)
        with store.connect() as db:
            rows = db.execute("SELECT id,email,role,full_name,position FROM users WHERE active=1 AND role IN (%s) ORDER BY full_name, id" % ",".join("?" for _ in roles), roles).fetchall()
        return {"users": [public_user(row) for row in rows]}

    @router.post("/api/staff/projects", status_code=201)
    def create_project(body: ProjectCreate, user: dict = Depends(manager)):
        pid = secrets.token_hex(16)
        with store.connect() as db:
            db.execute("INSERT INTO projects (id,title,owner_id,created_at) VALUES (?,?,?,?)", (pid, body.title, user["id"], iso(now())))
        return {"id": pid, "title": body.title}

    @router.get("/api/staff/projects")
    def projects(user: dict = Depends(ready_user)):
        with store.connect() as db:
            if user["role"] == "director":
                rows = db.execute("SELECT projects.*, CASE WHEN users.active=1 THEN users.full_name ELSE 'Удалённый пользователь' END AS owner_name, CASE WHEN users.active=1 THEN COALESCE(NULLIF(users.position,''), CASE users.role WHEN 'teacher' THEN 'Учитель' WHEN 'associate' THEN 'Заместитель директора' ELSE 'Директор' END) ELSE '' END AS owner_position FROM projects JOIN users ON users.id=projects.owner_id ORDER BY projects.created_at DESC").fetchall()
            else:
                rows = db.execute("SELECT projects.*, CASE WHEN users.active=1 THEN users.full_name ELSE 'Удалённый пользователь' END AS owner_name, CASE WHEN users.active=1 THEN COALESCE(NULLIF(users.position,''), CASE users.role WHEN 'teacher' THEN 'Учитель' WHEN 'associate' THEN 'Заместитель директора' ELSE 'Директор' END) ELSE '' END AS owner_position FROM projects JOIN users ON users.id=projects.owner_id WHERE projects.owner_id=? OR EXISTS (SELECT 1 FROM tasks WHERE tasks.project_id=projects.id AND (tasks.assignee_id=? OR EXISTS (SELECT 1 FROM task_collaborators tc WHERE tc.task_id=tasks.id AND tc.user_id=?))) ORDER BY projects.created_at DESC", (user["id"], user["id"], user["id"])).fetchall()
            projects = []
            for row in rows:
                project = dict(row)
                if user["role"] == "director" or row["owner_id"] == user["id"]:
                    counts = db.execute("SELECT COUNT(*) AS total, COALESCE(SUM(approved_at IS NOT NULL),0) AS approved FROM tasks WHERE project_id=?", (row["id"],)).fetchone()
                    project.update(total_tasks=counts["total"], approved_tasks=counts["approved"])
                projects.append(project)
        return {"projects": projects}

    @router.post("/api/staff/projects/{project_id}/complete")
    def complete_project(project_id: str, user: dict = Depends(manager)):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            project = db.execute("SELECT * FROM projects WHERE id=? AND owner_id=?", (project_id,user["id"])).fetchone()
            if not project:
                raise HTTPException(404, "Проект не найден")
            if project["finished_at"]:
                raise HTTPException(409, "Проект уже выполнен полностью")
            if db.execute("SELECT 1 FROM tasks WHERE project_id=? AND approved_at IS NULL LIMIT 1", (project_id,)).fetchone():
                raise HTTPException(409, "Сначала подтвердите полное выполнение всех задач проекта")
            finished=iso(now())
            db.execute("UPDATE projects SET finished_at=? WHERE id=?", (finished,project_id))
        return {"finished_at":finished}

    @router.post("/api/staff/tasks", status_code=201)
    def create_task(body: TaskCreate, user: dict = Depends(manager)):
        if body.deadline <= now():
            raise HTTPException(422, "Срок должен быть в будущем")
        tid = secrets.token_hex(16)
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            assignee = db.execute("SELECT role FROM users WHERE id=? AND active=1", (body.assignee_id,)).fetchone()
            allowed = ("associate", "teacher") if user["role"] == "director" else ("teacher",)
            if not assignee or assignee["role"] not in allowed:
                raise HTTPException(422, "Исполнитель не найден или недоступен для назначения")
            if body.project_id:
                project = db.execute("SELECT owner_id,finished_at FROM projects WHERE id=?", (body.project_id,)).fetchone()
                if not project:
                    raise HTTPException(404, "Проект не найден")
                if user["role"] != "director" and project["owner_id"] != user["id"]:
                    raise HTTPException(403, "Добавлять задачи может автор проекта или директор")
                if project["finished_at"]:
                    raise HTTPException(409, "Проект выполнен полностью")
            db.execute("INSERT INTO tasks (id,director_id,assignee_id,description,deadline,created_at,project_id) VALUES (?,?,?,?,?,?,?)", (tid, user["id"], body.assignee_id, body.description, iso(body.deadline), iso(now()), body.project_id))
            db.execute("INSERT INTO task_events VALUES (?,?,?,?,?)", (secrets.token_hex(16), tid, user["id"], "Задача создана", iso(now())))
            row = db.execute(TASK_SELECT + " WHERE tasks.id=?", (tid,)).fetchone()
        return {"task": task_json(row)}

    def task_access(user: dict):
        if user["role"] == "director":
            condition, params = "(tasks.director_id=? OR tasks.assignee_id=? OR tasks.project_id IS NOT NULL)", (user["id"], user["id"])
        elif user["role"] == "associate":
            condition, params = "(tasks.assignee_id=? OR tasks.director_id=? OR EXISTS (SELECT 1 FROM projects WHERE projects.id=tasks.project_id AND projects.owner_id=?))", (user["id"], user["id"], user["id"])
        else:
            condition, params = "tasks.assignee_id=?", (user["id"],)
        condition = f"({condition} OR EXISTS (SELECT 1 FROM task_collaborators tc WHERE tc.task_id=tasks.id AND tc.user_id=?))"
        return condition, (*params, user["id"])

    @router.get("/api/staff/tasks")
    def tasks(include_hidden: bool = False, user: dict = Depends(ready_user)):
        condition, params = task_access(user)
        with store.connect() as db:
            hidden_ids = {row[0] for row in db.execute("SELECT task_id FROM task_hidden WHERE user_id=?", (user["id"],))}
            rows = db.execute(TASK_SELECT + f" WHERE {condition} ORDER BY tasks.deadline ASC, tasks.created_at DESC", params).fetchall()
            collaborators = db.execute("""SELECT tc.task_id, u.id, CASE WHEN u.active=1 THEN u.full_name ELSE 'Удалённый пользователь' END AS full_name,
                CASE WHEN u.active=1 THEN COALESCE(NULLIF(u.position,''),CASE u.role WHEN 'teacher' THEN 'Учитель' WHEN 'associate' THEN 'Заместитель директора' ELSE 'Директор' END) ELSE '' END AS position
                FROM task_collaborators tc JOIN users u ON u.id=tc.user_id JOIN tasks ON tasks.id=tc.task_id WHERE """ + condition + " ORDER BY tc.added_at,tc.user_id", params).fetchall()
        grouped = {}
        for row in collaborators:
            grouped.setdefault(row["task_id"], []).append({key: row[key] for key in ("id", "full_name", "position")})
        return {"tasks": [task_json(row) | {"collaborators": grouped.get(row["id"], []), "hidden": row["id"] in hidden_ids} for row in rows if include_hidden or row["id"] not in hidden_ids]}

    @router.get("/api/staff/tasks/{task_id}/collaborators/candidates")
    def collaborator_candidates(task_id: str, user: dict = Depends(ready_user)):
        with store.connect() as db:
            task = db.execute("SELECT * FROM tasks WHERE id=? AND director_id=?", (task_id, user["id"])).fetchone()
            if not task:
                raise HTTPException(404, "Задача не найдена")
            if task["completed_at"]:
                raise HTTPException(409, "Задача уже выполнена")
            rows = db.execute("""SELECT id,full_name,position,role FROM users WHERE active=1 AND id NOT IN (?,?)
                AND NOT EXISTS (SELECT 1 FROM task_collaborators WHERE task_id=? AND user_id=users.id) ORDER BY full_name,id""", (task["director_id"], task["assignee_id"], task_id)).fetchall()
        return {"users": [dict(row) for row in rows]}

    @router.post("/api/staff/tasks/{task_id}/collaborators", status_code=201)
    def add_collaborator(task_id: str, body: CollaboratorAdd, user: dict = Depends(ready_user)):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = db.execute("SELECT * FROM tasks WHERE id=? AND director_id=?", (task_id, user["id"])).fetchone()
            if not task:
                raise HTTPException(404, "Задача не найдена")
            if task["completed_at"]:
                raise HTTPException(409, "Задача уже выполнена")
            target = db.execute("SELECT id,full_name,position,role FROM users WHERE id=? AND active=1", (body.user_id,)).fetchone()
            if not target or body.user_id in (task["director_id"], task["assignee_id"]):
                raise HTTPException(422, "Пользователь недоступен для добавления")
            try:
                db.execute("INSERT INTO task_collaborators VALUES (?,?,?)", (task_id, body.user_id, iso(now())))
            except sqlite3.IntegrityError:
                raise HTTPException(409, "Пользователь уже участвует в задаче")
        return {"user": dict(target)}

    def notify_initiator(db, task_id: str, actor_id: str, kind: str):
        db.execute("""INSERT INTO task_notifications (task_id, recipient_id, actor_id, kind, created_at)
            SELECT tasks.id, tasks.director_id, ?, ?, ? FROM tasks JOIN users ON users.id=tasks.director_id
            WHERE tasks.id=? AND tasks.director_id<>? AND users.active=1""", (actor_id, kind, iso(now()), task_id, actor_id))

    @router.get("/api/staff/notifications")
    def notifications(user: dict = Depends(ready_user)):
        with store.connect() as db:
            rows = db.execute("""SELECT n.id,n.task_id,n.kind,n.created_at,tasks.description,tasks.project_id,
                CASE WHEN actor.active=1 THEN actor.full_name ELSE 'Удалённый пользователь' END AS actor_name,
                CASE WHEN actor.active=1 THEN COALESCE(NULLIF(actor.position,''),CASE actor.role WHEN 'teacher' THEN 'Учитель' WHEN 'associate' THEN 'Заместитель директора' ELSE 'Директор' END) ELSE '' END AS actor_position
                FROM task_notifications n JOIN tasks ON tasks.id=n.task_id JOIN users actor ON actor.id=n.actor_id
                WHERE n.recipient_id=? AND n.read_at IS NULL ORDER BY n.id DESC""", (user["id"],)).fetchall()
        return {"notifications": [dict(row) for row in rows]}

    @router.post("/api/staff/tasks/{task_id}/notifications/read")
    def read_notifications(task_id: str, body: NotificationRead, user: dict = Depends(ready_user)):
        with store.connect() as db:
            db.execute("UPDATE task_notifications SET read_at=? WHERE task_id=? AND recipient_id=? AND read_at IS NULL AND id<=?", (iso(now()), task_id, user["id"], body.through_id))
        return {"ok": True}

    @router.put("/api/staff/tasks/{task_id}/completion")
    def complete_task(task_id: str, body: Complete, user: dict = Depends(ready_user)):
        if not body.completed and not body.expected_completed_at:
            raise HTTPException(400, "Обновите задачу перед снятием отметки")
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT completed_at,cycle,approved_at FROM tasks WHERE id=? AND assignee_id=?", (task_id, user["id"])).fetchone()
            if not previous:
                raise HTTPException(404, "Задача не найдена")
            if previous["cycle"] != body.cycle:
                raise HTTPException(409, "Состояние задачи изменилось. Обновите страницу.")
            if body.completed:
                if not previous["completed_at"]:
                    db.execute("UPDATE tasks SET completed_at=?, partial=0,rework=0 WHERE id=?", (iso(now()), task_id))
                    db.execute("INSERT INTO task_events VALUES (?,?,?,?,?)", (secrets.token_hex(16), task_id, user["id"], "Задача выполнена", iso(now())))
                    notify_initiator(db, task_id, user["id"], "completed")
            else:
                if previous["approved_at"]:
                    raise HTTPException(409, "Инициатор уже подтвердил полное выполнение задачи")
                if not previous["completed_at"] or previous["completed_at"] != body.expected_completed_at:
                    raise HTTPException(409, "Состояние задачи изменилось. Обновите страницу.")
                db.execute("UPDATE tasks SET completed_at=NULL,cycle=cycle+1 WHERE id=?", (task_id,))
                text = f"Исполнитель снял отметку выполнения (отмечено ранее: {previous['completed_at']})"
                db.execute("INSERT INTO task_events VALUES (?,?,?,?,?)", (secrets.token_hex(16), task_id, user["id"], text, iso(now())))
                notify_initiator(db, task_id, user["id"], "completion_undone")
            task = db.execute(TASK_SELECT + " WHERE tasks.id=?", (task_id,)).fetchone()
        return {"task": task_json(task)}

    @router.post("/api/staff/tasks/{task_id}/approve")
    def approve_task(task_id: str, body: ReworkApproval, user: dict = Depends(ready_user)):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tasks WHERE id=? AND director_id=?", (task_id, user["id"])).fetchone()
            if not row:
                raise HTTPException(404, "Задача не найдена")
            if row["approved_at"]:
                raise HTTPException(409, "Задача уже подтверждена")
            if not row["completed_at"] or row["completed_at"] != body.expected_completed_at:
                raise HTTPException(409, "Состояние задачи изменилось. Обновите страницу.")
            db.execute("UPDATE tasks SET approved_at=? WHERE id=?", (iso(now()), task_id))
            db.execute("INSERT INTO task_events VALUES (?,?,?,?,?)", (secrets.token_hex(16), task_id, user["id"], "Инициатор подтвердил: выполнено полностью", iso(now())))
            db.execute("""INSERT INTO task_notifications (task_id,recipient_id,actor_id,kind,created_at)
                SELECT ?,u.id,?,'approved',? FROM users u WHERE u.active=1 AND u.id<>? AND (u.id=? OR EXISTS (SELECT 1 FROM task_collaborators c WHERE c.task_id=? AND c.user_id=u.id))""",
                (task_id,user["id"],iso(now()),user["id"],row["assignee_id"],task_id))
            task = db.execute(TASK_SELECT + " WHERE tasks.id=?", (task_id,)).fetchone()
        return {"task": task_json(task)}

    @router.post("/api/staff/tasks/{task_id}/hide")
    def hide_task(task_id: str, user: dict = Depends(ready_user)):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Задача не найдена")
            participant = row["assignee_id"] == user["id"] or db.execute("SELECT 1 FROM task_collaborators WHERE task_id=? AND user_id=?", (task_id,user["id"])).fetchone()
            if row["director_id"] != user["id"] and not participant:
                raise HTTPException(404, "Задача не найдена")
            if row["director_id"] != user["id"] and not row["approved_at"]:
                raise HTTPException(409, "Удалить задачу можно после подтверждения инициатором")
            db.execute("INSERT OR IGNORE INTO task_hidden VALUES (?,?,?)", (task_id,user["id"],iso(now())))
            db.execute("UPDATE task_notifications SET read_at=? WHERE task_id=? AND recipient_id=? AND read_at IS NULL", (iso(now()),task_id,user["id"]))
        return {"ok":True}

    @router.post("/api/staff/tasks/{task_id}/restore")
    def restore_task(task_id: str, user: dict = Depends(ready_user)):
        with store.connect() as db:
            result = db.execute("DELETE FROM task_hidden WHERE task_id=? AND user_id=?", (task_id,user["id"]))
            if not result.rowcount:
                raise HTTPException(404, "Задача не найдена")
        return {"ok":True}

    @router.post("/api/staff/tasks/{task_id}/rework")
    def return_for_rework(task_id: str, body: Rework, user: dict = Depends(ready_user)):
        if body.deadline <= now():
            raise HTTPException(422, "Новый срок должен быть в будущем")
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tasks WHERE id=? AND director_id=?", (task_id, user["id"])).fetchone()
            if not row:
                raise HTTPException(404, "Задача не найдена")
            if row["approved_at"]:
                raise HTTPException(409, "Задача подтверждена как полностью выполненная")
            if not row["completed_at"] or row["completed_at"] != body.expected_completed_at:
                raise HTTPException(409, "Состояние задачи изменилось. Обновите страницу.")
            new_deadline = iso(body.deadline)
            db.execute("UPDATE tasks SET completed_at=NULL,deadline=?,partial=0,failure_reason='',rework=1,cycle=cycle+1 WHERE id=?", (new_deadline, task_id))
            text = (f"Возвращено на доработку. Причина: {body.comment}\n"
                    f"Предыдущая отметка выполнения: {row['completed_at']}; прежний срок: {row['deadline']}; новый срок: {new_deadline}"
                    + (f"\nРанее указанная причина невыполнения: {row['failure_reason']}" if row["failure_reason"] else ""))
            db.execute("INSERT INTO task_events VALUES (?,?,?,?,?)", (secrets.token_hex(16), task_id, user["id"], text, iso(now())))
            db.execute("""INSERT INTO task_notifications (task_id, recipient_id, actor_id, kind, created_at)
                SELECT tasks.id,tasks.assignee_id,?,'rework',? FROM tasks JOIN users ON users.id=tasks.assignee_id
                WHERE tasks.id=? AND tasks.assignee_id<>? AND users.active=1""", (user["id"], iso(now()), task_id, user["id"]))
            task = db.execute(TASK_SELECT + " WHERE tasks.id=?", (task_id,)).fetchone()
        return {"task": task_json(task)}

    @router.put("/api/staff/tasks/{task_id}/progress")
    def update_progress(task_id: str, body: TaskProgress, user: dict = Depends(ready_user)):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT completed_at FROM tasks WHERE id=? AND assignee_id=?", (task_id, user["id"])).fetchone()
            if not row:
                raise HTTPException(404, "Задача не найдена")
            if row["completed_at"]:
                raise HTTPException(409, "Задача уже выполнена")
            db.execute("UPDATE tasks SET partial=?,failure_reason=? WHERE id=?", (int(body.partial), body.reason, task_id))
            text = ("Отмечено частичное выполнение" if body.partial else "Частичная отметка снята") + (f". Причина невыполнения: {body.reason}" if body.reason else ". Причина невыполнения не указана")
            db.execute("INSERT INTO task_events VALUES (?,?,?,?,?)", (secrets.token_hex(16), task_id, user["id"], text, iso(now())))
            task = db.execute(TASK_SELECT + " WHERE tasks.id=?", (task_id,)).fetchone()
        return {"task": task_json(task)}

    def check_task_access(db, task_id: str, user: dict):
        condition, params = task_access(user)
        if not db.execute(f"SELECT 1 FROM tasks WHERE tasks.id=? AND {condition}", (task_id, *params)).fetchone():
            raise HTTPException(404, "Задача не найдена")

    @router.get("/api/staff/tasks/{task_id}/comments")
    def comments(task_id: str, user: dict = Depends(ready_user)):
        with store.connect() as db:
            db.execute("BEGIN")
            check_task_access(db, task_id, user)
            rows = db.execute("""SELECT task_comments.id, task_comments.text, task_comments.created_at,
                CASE WHEN users.active=1 THEN users.full_name ELSE 'Удалённый пользователь' END AS author_name,
                CASE WHEN users.active=1 THEN COALESCE(NULLIF(users.position,''), CASE users.role WHEN 'teacher' THEN 'Учитель' WHEN 'associate' THEN 'Заместитель директора' ELSE 'Директор' END) ELSE '' END AS author_position
                FROM task_comments JOIN users ON users.id=task_comments.author_id WHERE task_comments.task_id=? ORDER BY task_comments.created_at,task_comments.id""", (task_id,)).fetchall()
            events = db.execute("""SELECT task_events.id, task_events.text, task_events.created_at,
                CASE WHEN users.active=1 THEN users.full_name ELSE 'Удалённый пользователь' END AS author_name,
                CASE WHEN users.active=1 THEN COALESCE(NULLIF(users.position,''), CASE users.role WHEN 'teacher' THEN 'Учитель' WHEN 'associate' THEN 'Заместитель директора' ELSE 'Директор' END) ELSE '' END AS author_position
                FROM task_events JOIN users ON users.id=task_events.author_id WHERE task_events.task_id=? ORDER BY task_events.created_at,task_events.id""", (task_id,)).fetchall()
            through = db.execute("SELECT MAX(id) FROM task_notifications WHERE task_id=? AND recipient_id=? AND read_at IS NULL", (task_id, user["id"])).fetchone()[0]
        return {"comments": [dict(row) for row in rows], "events": visible_task_events(events), "notification_through_id": through}

    @router.post("/api/staff/tasks/{task_id}/comments", status_code=201)
    def add_comment(task_id: str, body: TaskComment, user: dict = Depends(ready_user)):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            check_task_access(db, task_id, user)
            db.execute("INSERT INTO task_comments VALUES (?,?,?,?,?)", (secrets.token_hex(16), task_id, user["id"], body.text, iso(now())))
            notify_initiator(db, task_id, user["id"], "comment")
            # Исполнитель тоже получает комментарии от автора и соисполнителей,
            # но не уведомления о собственных сообщениях.
            db.execute("""INSERT INTO task_notifications (task_id, recipient_id, actor_id, kind, created_at)
                SELECT tasks.id, tasks.assignee_id, ?, 'comment', ? FROM tasks JOIN users ON users.id=tasks.assignee_id
                WHERE tasks.id=? AND tasks.assignee_id<>? AND tasks.assignee_id<>tasks.director_id AND users.active=1""",
                (user["id"], iso(now()), task_id, user["id"]))
        return {"ok": True}

    return router
