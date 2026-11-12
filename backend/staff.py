"""Private staff accounts and task workflow, stored outside the public schedule backup."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import smtplib
import sqlite3
import ssl
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException
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


def send_registration(email: str, role: str, password: str) -> None:
    host = os.environ.get("SMTP_HOST", "").strip()
    sender = os.environ.get("SMTP_FROM", "").strip()
    username, secret = os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASSWORD", "")
    security = os.environ.get("SMTP_SECURITY", "starttls").lower()
    if not host or not sender or security not in ("ssl", "starttls"):
        raise RuntimeError("SMTP не настроен: укажите SMTP_HOST, SMTP_FROM и защищённый режим SMTP_SECURITY.")
    base_url = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if base_url:
        try:
            parts = urlsplit(base_url)
            valid_url = parts.scheme == "https" and parts.hostname and not (parts.path or parts.query or parts.fragment or parts.username or parts.password)
        except ValueError:
            valid_url = False
        if not valid_url:
            raise RuntimeError("PUBLIC_BASE_URL должен содержать HTTPS-адрес сайта без пути.")
    try:
        port = int(os.environ.get("SMTP_PORT", "465" if security == "ssl" else "587"))
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = email
        msg["Subject"] = "Доступ к сервису расписания"
        path = "/Director" if role == "director" else "/associate"
        address = base_url + path if base_url else f"откройте сайт сервиса и перейдите на {path}"
        msg.set_content(f"Здравствуйте!\n\nДля вас создана учётная запись.\nСтраница входа: {address}\nЛогин: {email}\nВременный пароль: {password}\n\nПри первом входе необходимо сменить пароль. Не пересылайте это письмо и удалите его после смены пароля.\n")
        context = ssl.create_default_context()
        if security == "ssl":
            client = smtplib.SMTP_SSL(host, port, timeout=15, context=context)
        else:
            client = smtplib.SMTP(host, port, timeout=15)
        with client:
            if security == "starttls":
                client.starttls(context=context)
            if username:
                client.login(username, secret)
            client.send_message(msg)
    except Exception as exc:
        raise RuntimeError("Не удалось отправить письмо через SMTP. Проверьте настройки почты и доступность сервера.") from exc


class NewUser(BaseModel):
    email: EmailStr
    role: Literal["director", "associate"]


class Login(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    role: Literal["director", "associate"]


class PasswordChange(BaseModel):
    password: str = Field(min_length=12, max_length=256)


class TaskCreate(BaseModel):
    assignee_id: str
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
                    role TEXT NOT NULL CHECK (role IN ('director','associate')),
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
        self.path.chmod(0o600)


def public_user(user) -> dict:
    return {key: user[key] for key in ("id", "email", "role")}


def task_json(row, current: datetime | None = None) -> dict:
    due = datetime.fromisoformat(row["deadline"])
    completed = datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None
    current = current or now()
    status = ("completed_on_time" if completed <= due else "completed_late") if completed else ("overdue" if current > due else "pending")
    return {key: row[key] for key in ("id", "description", "deadline", "created_at", "completed_at", "assignee_id", "assignee_email", "director_email")} | {"status": status}


TASK_SELECT = '''SELECT tasks.*, assignee.email AS assignee_email, director.email AS director_email
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

    @router.get("/api/admin/users")
    def list_users(_: None = Depends(require_admin)):
        with store.connect() as db:
            rows = db.execute("SELECT id,email,role FROM users WHERE active=1 ORDER BY email").fetchall()
        return {"users": [public_user(row) for row in rows]}

    @router.post("/api/admin/users", status_code=201)
    def create_user(body: NewUser, _: None = Depends(require_admin)):
        email = str(body.email).strip().lower()
        uid, password = secrets.token_hex(16), secrets.token_urlsafe(18)
        try:
            with store.connect() as db:
                db.execute("INSERT INTO users (id,email,role,password_hash,created_at) VALUES (?,?,?,?,?)", (uid, email, body.role, hash_password(password), iso(now())))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Пользователь с таким e-mail уже существует")
        try:
            send_registration(email, body.role, password)
        except RuntimeError as exc:
            with store.connect() as db:
                db.execute("DELETE FROM users WHERE id=? AND active=0", (uid,))
            raise HTTPException(503, str(exc))
        with store.connect() as db:
            db.execute("UPDATE users SET active=1 WHERE id=?", (uid,))
        return {"user": {"id": uid, "email": email, "role": body.role}, "message": "Письмо отправлено"}

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

    @router.post("/api/staff/logout")
    def logout(user: dict = Depends(require_staff)):
        with store.connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (user["token_hash"],))
        return {"ok": True}

    @router.post("/api/staff/password")
    def change_password(body: PasswordChange, user: dict = Depends(require_staff)):
        if check_password(body.password, user["password_hash"]):
            raise HTTPException(422, "Новый пароль должен отличаться от текущего")
        with store.connect() as db:
            db.execute("UPDATE users SET password_hash=?, must_change=0 WHERE id=?", (hash_password(body.password), user["id"]))
            db.execute("DELETE FROM sessions WHERE user_id=? AND token_hash<>?", (user["id"], user["token_hash"]))
        return {"ok": True}

    @router.get("/api/staff/associates")
    def associates(_: dict = Depends(director)):
        with store.connect() as db:
            rows = db.execute("SELECT id,email,role FROM users WHERE role='associate' AND active=1 ORDER BY email").fetchall()
        return {"users": [public_user(row) for row in rows]}

    @router.post("/api/staff/tasks", status_code=201)
    def create_task(body: TaskCreate, user: dict = Depends(director)):
        if body.deadline <= now():
            raise HTTPException(422, "Срок должен быть в будущем")
        tid = secrets.token_hex(16)
        with store.connect() as db:
            assignee = db.execute("SELECT id FROM users WHERE id=? AND role='associate' AND active=1", (body.assignee_id,)).fetchone()
            if not assignee:
                raise HTTPException(422, "Заместитель не найден")
            db.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?,NULL)", (tid, user["id"], body.assignee_id, body.description, iso(body.deadline), iso(now())))
            row = db.execute(TASK_SELECT + " WHERE tasks.id=?", (tid,)).fetchone()
        return {"task": task_json(row)}

    @router.get("/api/staff/tasks")
    def tasks(user: dict = Depends(ready_user)):
        column = "director_id" if user["role"] == "director" else "assignee_id"
        with store.connect() as db:
            rows = db.execute(TASK_SELECT + f" WHERE tasks.{column}=? ORDER BY tasks.deadline ASC, tasks.created_at DESC", (user["id"],)).fetchall()
        return {"tasks": [task_json(row) for row in rows]}

    @router.put("/api/staff/tasks/{task_id}/completion")
    def complete_task(task_id: str, body: Complete, user: dict = Depends(ready_user)):
        if user["role"] != "associate":
            raise HTTPException(403, "Отметить выполнение может только назначенный заместитель")
        if not body.completed:
            raise HTTPException(400, "Отметку выполнения нельзя отменить")
        with store.connect() as db:
            updated = db.execute("UPDATE tasks SET completed_at=COALESCE(completed_at, ?) WHERE id=? AND assignee_id=?", (iso(now()), task_id, user["id"]))
            if not updated.rowcount:
                raise HTTPException(404, "Задача не найдена")
            task = db.execute(TASK_SELECT + " WHERE tasks.id=?", (task_id,)).fetchone()
        return {"task": task_json(task)}

    return router
