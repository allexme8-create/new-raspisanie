"""Private staff accounts and task workflow, stored outside the public schedule backup."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, EmailStr, Field, field_validator

SESSION_TTL = 12 * 60 * 60


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


class Complete(BaseModel):
    completed: bool


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
            task_columns = {row["name"] for row in db.execute("PRAGMA table_info(tasks)")}
            if "project_id" not in task_columns:
                db.execute("ALTER TABLE tasks ADD COLUMN project_id TEXT REFERENCES projects(id)")
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


def task_json(row, current: datetime | None = None) -> dict:
    due = datetime.fromisoformat(row["deadline"])
    completed = datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None
    current = current or now()
    status = ("completed_on_time" if completed <= due else "completed_late") if completed else ("overdue" if current > due else "pending")
    return {key: row[key] for key in ("id", "description", "deadline", "created_at", "completed_at", "assignee_id", "assignee_email", "director_email", "assignee_name", "director_name", "project_id", "director_id", "assignee_position", "director_position")} | {"status": status}


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
                db.execute("INSERT INTO users (id,email,role,password_hash,password_ciphertext,must_change,active,created_at,position) VALUES (?,?,?,?,?,1,1,?,?)", (uid, email, body.role, hash_password(password), encrypted, iso(now()), body.position))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Пользователь с таким e-mail уже существует")
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        return {"user": {"id": uid, "email": email, "role": body.role, "full_name": "", "position": body.position}, "password": password}

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

    @router.get("/api/staff/associates")
    def associates(_: dict = Depends(director)):
        with store.connect() as db:
            rows = db.execute("SELECT id,email,role,full_name,position FROM users WHERE role='associate' AND active=1 ORDER BY email").fetchall()
        return {"users": [public_user(row) for row in rows]}

    def manager(user: dict = Depends(ready_user)) -> dict:
        if user["role"] not in ("director", "associate"):
            raise HTTPException(403, "Доступ только для руководства")
        return user

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
            db.execute("INSERT INTO projects VALUES (?,?,?,?)", (pid, body.title, user["id"], iso(now())))
        return {"id": pid, "title": body.title}

    @router.get("/api/staff/projects")
    def projects(user: dict = Depends(ready_user)):
        with store.connect() as db:
            if user["role"] == "director":
                rows = db.execute("SELECT projects.*, CASE WHEN users.active=1 THEN users.full_name ELSE 'Удалённый пользователь' END AS owner_name, CASE WHEN users.active=1 THEN COALESCE(NULLIF(users.position,''), CASE users.role WHEN 'teacher' THEN 'Учитель' WHEN 'associate' THEN 'Заместитель директора' ELSE 'Директор' END) ELSE '' END AS owner_position FROM projects JOIN users ON users.id=projects.owner_id ORDER BY projects.created_at DESC").fetchall()
            else:
                rows = db.execute("SELECT projects.*, CASE WHEN users.active=1 THEN users.full_name ELSE 'Удалённый пользователь' END AS owner_name, CASE WHEN users.active=1 THEN COALESCE(NULLIF(users.position,''), CASE users.role WHEN 'teacher' THEN 'Учитель' WHEN 'associate' THEN 'Заместитель директора' ELSE 'Директор' END) ELSE '' END AS owner_position FROM projects JOIN users ON users.id=projects.owner_id WHERE projects.owner_id=? OR EXISTS (SELECT 1 FROM tasks WHERE tasks.project_id=projects.id AND tasks.assignee_id=?) ORDER BY projects.created_at DESC", (user["id"], user["id"])).fetchall()
        return {"projects": [dict(row) for row in rows]}

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
                project = db.execute("SELECT owner_id FROM projects WHERE id=?", (body.project_id,)).fetchone()
                if not project:
                    raise HTTPException(404, "Проект не найден")
                if user["role"] != "director" and project["owner_id"] != user["id"]:
                    raise HTTPException(403, "Добавлять задачи может автор проекта или директор")
            db.execute("INSERT INTO tasks (id,director_id,assignee_id,description,deadline,created_at,project_id) VALUES (?,?,?,?,?,?,?)", (tid, user["id"], body.assignee_id, body.description, iso(body.deadline), iso(now()), body.project_id))
            row = db.execute(TASK_SELECT + " WHERE tasks.id=?", (tid,)).fetchone()
        return {"task": task_json(row)}

    @router.get("/api/staff/tasks")
    def tasks(user: dict = Depends(ready_user)):
        if user["role"] == "director":
            condition, params = "(tasks.director_id=? OR tasks.assignee_id=? OR tasks.project_id IS NOT NULL)", (user["id"], user["id"])
        elif user["role"] == "associate":
            condition, params = "(tasks.assignee_id=? OR tasks.director_id=? OR EXISTS (SELECT 1 FROM projects WHERE projects.id=tasks.project_id AND projects.owner_id=?))", (user["id"], user["id"], user["id"])
        else:
            condition, params = "tasks.assignee_id=?", (user["id"],)
        with store.connect() as db:
            rows = db.execute(TASK_SELECT + f" WHERE {condition} ORDER BY tasks.deadline ASC, tasks.created_at DESC", params).fetchall()
        return {"tasks": [task_json(row) for row in rows]}

    @router.put("/api/staff/tasks/{task_id}/completion")
    def complete_task(task_id: str, body: Complete, user: dict = Depends(ready_user)):
        if not body.completed:
            raise HTTPException(400, "Отметку выполнения нельзя отменить")
        with store.connect() as db:
            updated = db.execute("UPDATE tasks SET completed_at=COALESCE(completed_at, ?) WHERE id=? AND assignee_id=?", (iso(now()), task_id, user["id"]))
            if not updated.rowcount:
                raise HTTPException(404, "Задача не найдена")
            task = db.execute(TASK_SELECT + " WHERE tasks.id=?", (task_id,)).fetchone()
        return {"task": task_json(task)}

    return router
