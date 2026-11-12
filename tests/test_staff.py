from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import staff


def admin(authorization: str = Header(default="")):
    if authorization != "Bearer admin":
        raise HTTPException(401, "Требуется администратор")


class StaffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = staff.Store(Path(self.tmp.name) / "staff.sqlite3")
        app = FastAPI()
        app.include_router(staff.make_router(self.store, admin))
        self.client = TestClient(app)
        self.admin = {"Authorization": "Bearer admin"}

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def create(self, email, role):
        response = self.client.post("/api/admin/users", headers=self.admin, json={"email": email, "role": role})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def login(self, email, role, password):
        return self.client.post("/api/staff/login", json={"email": email, "role": role, "password": password})

    def ready(self, email, role, password):
        login = self.login(email, role, password)
        self.assertEqual(login.status_code, 200, login.text)
        headers = {"Authorization": "Bearer " + login.json()["token"]}
        self.assertEqual(self.client.get("/api/staff/tasks", headers=headers).status_code, 403)
        new_password = "новый пароль очень надёжный"
        self.assertEqual(self.client.post("/api/staff/password", headers=headers, json={"password": new_password}).status_code, 200)
        return headers, new_password

    def test_create_reveal_and_change_password(self):
        self.assertEqual(self.client.post("/api/admin/users", json={"email": "a@example.com", "role": "director"}).status_code, 401)
        created = self.create("a@example.com", "director")
        uid, password = created["user"]["id"], created["password"]
        self.assertGreaterEqual(len(password), 16)
        self.assertTrue(self.store.key_path.exists())
        self.assertEqual(os.stat(self.store.key_path).st_mode & 0o777, 0o600)
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            self.assertNotIn(password, row["password_hash"])
            self.assertNotIn(password, row["password_ciphertext"])
            self.assertTrue(staff.check_password(password, row["password_hash"]))
        self.assertNotIn(password, self.client.get("/api/admin/users", headers=self.admin).text)
        url = f"/api/admin/users/{uid}/password"
        self.assertEqual(self.client.post(url).status_code, 401)
        self.assertEqual(self.client.post(url, headers=self.admin).json()["password"], password)
        headers, changed = self.ready("a@example.com", "director", password)
        self.assertEqual(self.client.post(url, headers=headers).status_code, 401)
        self.assertEqual(self.client.post(url, headers=self.admin).json()["password"], changed)
        self.assertEqual(self.login("a@example.com", "director", password).status_code, 401)
        self.assertEqual(self.login("a@example.com", "director", changed).status_code, 200)
        self.assertEqual(self.client.post("/api/admin/users", headers=self.admin, json={"email": "A@example.com", "role": "associate"}).status_code, 409)

    def test_reset_revokes_sessions_and_requires_change(self):
        created = self.create("a@example.com", "associate")
        uid, initial = created["user"]["id"], created["password"]
        session, changed = self.ready("a@example.com", "associate", initial)
        url = f"/api/admin/users/{uid}/password/reset"
        self.assertEqual(self.client.post(url, headers=session).status_code, 401)
        response = self.client.post(url, headers=self.admin)
        new = response.json()["password"]
        self.assertNotEqual(new, changed)
        self.assertEqual(self.client.get("/api/staff/me", headers=session).status_code, 401)
        self.assertEqual(self.login("a@example.com", "associate", changed).status_code, 401)
        login = self.login("a@example.com", "associate", new)
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.json()["must_change"])
        self.assertEqual(self.client.post(f"/api/admin/users/{uid}/password", headers=self.admin).json()["password"], new)

    def test_legacy_account_keeps_login_and_admin_can_reset(self):
        old_password = "старый длинный пароль"
        with self.store.connect() as db:
            db.execute("INSERT INTO users(id,email,role,password_hash,must_change,active,created_at) VALUES(?,?,?,?,0,1,?)", ("legacy", "old@example.com", "director", staff.hash_password(old_password), staff.iso(staff.now())))
        self.store.init()
        self.assertEqual(self.login("old@example.com", "director", old_password).status_code, 200)
        reveal = self.client.post("/api/admin/users/legacy/password", headers=self.admin)
        self.assertEqual(reveal.status_code, 409)
        new = self.client.post("/api/admin/users/legacy/password/reset", headers=self.admin).json()["password"]
        self.assertEqual(self.client.post("/api/admin/users/legacy/password", headers=self.admin).json()["password"], new)

    def test_lost_or_wrong_key_does_not_regenerate_or_overwrite(self):
        created = self.create("a@example.com", "associate")
        uid = created["user"]["id"]
        original_key = self.store.key_path.read_bytes()
        self.store.key_path.unlink()
        self.assertEqual(self.client.post(f"/api/admin/users/{uid}/password", headers=self.admin).status_code, 503)
        self.assertEqual(self.client.post(f"/api/admin/users/{uid}/password/reset", headers=self.admin).status_code, 503)
        self.assertFalse(self.store.key_path.exists())
        self.store.key_path.write_bytes(staff.Fernet.generate_key())
        self.assertEqual(self.client.post(f"/api/admin/users/{uid}/password/reset", headers=self.admin).status_code, 503)
        self.store.key_path.write_bytes(original_key)
        self.assertEqual(self.client.post(f"/api/admin/users/{uid}/password", headers=self.admin).json()["password"], created["password"])

    def test_existing_schema_migrates(self):
        path = Path(self.tmp.name) / "old.sqlite3"
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE users (id TEXT PRIMARY KEY,email TEXT UNIQUE,role TEXT,password_hash TEXT,must_change INTEGER,active INTEGER,created_at TEXT)")
            db.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?)", ("u", "old@example.com", "director", staff.hash_password("old-password"), 0, 1, staff.iso(staff.now())))
            db.execute("CREATE TABLE mail_oauth (id INTEGER)")
            db.execute("CREATE TABLE password_resets (user_id TEXT)")
        old = staff.Store(path)
        old.init()
        old.init()
        with old.connect() as db:
            self.assertIsNone(db.execute("SELECT password_ciphertext FROM users WHERE id='u'").fetchone()[0])
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='mail_oauth'").fetchone())
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='password_resets'").fetchone())

    def test_tasks_permissions_and_deletion(self):
        director_data = self.create("director@example.com", "director")
        deputy_data = self.create("deputy@example.com", "associate")
        director, _ = self.ready("director@example.com", "director", director_data["password"])
        deputy, _ = self.ready("deputy@example.com", "associate", deputy_data["password"])
        self.assertEqual(self.client.get("/api/staff/associates", headers=deputy).status_code, 403)
        body = {"assignee_id": deputy_data["user"]["id"], "description": "Отчёт", "deadline": (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}
        self.assertEqual(self.client.post("/api/staff/tasks", headers=deputy, json=body).status_code, 403)
        task = self.client.post("/api/staff/tasks", headers=director, json=body).json()["task"]
        url = f"/api/staff/tasks/{task['id']}/completion"
        self.assertEqual(self.client.put(url, headers=deputy, json={"completed": True}).json()["task"]["status"], "completed_on_time")
        self.assertEqual(self.client.put(url, headers=deputy, json={"completed": False}).status_code, 400)
        self.assertEqual(self.client.delete("/api/admin/users/"+deputy_data["user"]["id"], headers=deputy).status_code, 401)
        self.assertEqual(self.client.delete("/api/admin/users/"+deputy_data["user"]["id"], headers=self.admin).status_code, 200)
        self.assertEqual(self.client.get("/api/staff/me", headers=deputy).status_code, 401)
        self.assertEqual(self.client.get("/api/staff/tasks", headers=director).json()["tasks"][0]["assignee_email"], "Удалённый пользователь")
        recreated = self.create("deputy@example.com", "associate")
        self.assertNotEqual(recreated["user"]["id"], deputy_data["user"]["id"])
        self.assertEqual(self.client.post("/api/staff/password-reset/request", json={"email": "deputy@example.com", "role": "associate"}).status_code, 404)

    def test_bruteforce_throttle(self):
        user = self.create("a@example.com", "associate")
        for _ in range(5):
            self.assertEqual(self.login("a@example.com", "associate", "wrong").status_code, 401)
        self.assertEqual(self.login("a@example.com", "associate", user["password"]).status_code, 429)
        new = self.client.post(f"/api/admin/users/{user['user']['id']}/password/reset", headers=self.admin).json()["password"]
        self.assertEqual(self.login("a@example.com", "associate", new).status_code, 200)


if __name__ == "__main__":
    unittest.main()
