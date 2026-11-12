from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

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
        self.passwords = {}
        self.sender = patch.object(staff, "send_registration", side_effect=lambda email, role, password: self.passwords.update({email: password}))
        self.sender.start()

    def tearDown(self):
        self.sender.stop()
        self.client.close()
        self.tmp.cleanup()

    def create(self, email, role):
        response = self.client.post("/api/admin/users", headers=self.admin, json={"email": email, "role": role})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertNotIn(self.passwords[email], response.text)
        return response.json()["user"]

    def login(self, email, role):
        response = self.client.post("/api/staff/login", json={"email": email, "role": role, "password": self.passwords[email]})
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": "Bearer " + response.json()["token"]}

    def ready(self, email, role):
        headers = self.login(email, role)
        self.assertEqual(self.client.get("/api/staff/tasks", headers=headers).status_code, 403)
        response = self.client.post("/api/staff/password", headers=headers, json={"password": "новый пароль очень надёжный"})
        self.assertEqual(response.status_code, 200, response.text)
        return headers

    def test_registration_failure_is_rolled_back_and_secrets_hashed(self):
        self.assertEqual(self.client.post("/api/admin/users", json={"email": "a@example.com", "role": "director"}).status_code, 401)
        with patch.object(staff, "send_registration", side_effect=RuntimeError("SMTP не настроен")):
            resp = self.client.post("/api/admin/users", headers=self.admin, json={"email": "a@example.com", "role": "director"})
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(self.client.get("/api/admin/users", headers=self.admin).json()["users"], [])
        self.create("a@example.com", "director")
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM users").fetchone()
            self.assertNotIn(self.passwords["a@example.com"], row["password_hash"])
            self.assertTrue(staff.check_password(self.passwords["a@example.com"], row["password_hash"]))
        self.assertEqual(self.client.post("/api/admin/users", headers=self.admin, json={"email": "A@example.com", "role": "associate"}).status_code, 409)

    def test_workflow_permissions_and_statuses(self):
        self.create("director@example.com", "director")
        assistant = self.create("deputy@example.com", "associate")
        self.create("other@example.com", "associate")
        director = self.ready("director@example.com", "director")
        deputy = self.ready("deputy@example.com", "associate")
        other = self.ready("other@example.com", "associate")
        self.assertEqual(self.client.get("/api/admin/users", headers=director).status_code, 401)
        self.assertEqual(self.client.get("/api/staff/associates", headers=deputy).status_code, 403)
        deadline = datetime.now(timezone.utc) + timedelta(hours=1)
        body = {"assignee_id": assistant["id"], "description": "Подготовить отчёт", "deadline": deadline.isoformat()}
        self.assertEqual(self.client.post("/api/staff/tasks", headers=deputy, json=body).status_code, 403)
        response = self.client.post("/api/staff/tasks", headers=director, json=body)
        self.assertEqual(response.status_code, 201, response.text)
        task = response.json()["task"]
        self.assertEqual(task["status"], "pending")
        self.assertEqual(self.client.get("/api/staff/tasks", headers=other).json()["tasks"], [])
        url = "/api/staff/tasks/" + task["id"] + "/completion"
        self.assertEqual(self.client.put(url, headers=other, json={"completed": True}).status_code, 404)
        self.assertEqual(self.client.put(url, headers=director, json={"completed": True}).status_code, 403)
        with patch.object(staff, "now", return_value=deadline + timedelta(minutes=1)):
            self.assertEqual(self.client.get("/api/staff/tasks", headers=director).json()["tasks"][0]["status"], "overdue")
            done = self.client.put(url, headers=deputy, json={"completed": True}).json()["task"]
            self.assertEqual(done["status"], "completed_late")
            again = self.client.put(url, headers=deputy, json={"completed": True}).json()["task"]
            self.assertEqual(done["completed_at"], again["completed_at"])
        self.assertEqual(self.client.put(url, headers=deputy, json={"completed": False}).status_code, 400)
        self.assertEqual(self.client.get("/api/staff/tasks", headers=director).json()["tasks"][0]["status"], "completed_late")
        self.assertEqual(self.client.post("/api/staff/logout", headers=deputy).status_code, 200)
        self.assertEqual(self.client.get("/api/staff/me", headers=deputy).status_code, 401)

    def test_on_time_timezone_validation_and_wrong_role(self):
        self.create("director@example.com", "director")
        deputy = self.create("deputy@example.com", "associate")
        bad = self.client.post("/api/staff/login", json={"email": "director@example.com", "password": self.passwords["director@example.com"], "role": "associate"})
        self.assertEqual(bad.status_code, 401)
        director = self.ready("director@example.com", "director")
        worker = self.ready("deputy@example.com", "associate")
        body = {"assignee_id": deputy["id"], "description": "Проверка", "deadline": "2099-01-01T12:00:00"}
        self.assertEqual(self.client.post("/api/staff/tasks", headers=director, json=body).status_code, 422)
        body["deadline"] += "+07:00"
        task = self.client.post("/api/staff/tasks", headers=director, json=body).json()["task"]
        self.assertEqual(task["deadline"], "2099-01-01T05:00:00+00:00")
        completed = self.client.put(f"/api/staff/tasks/{task['id']}/completion", headers=worker, json={"completed": True}).json()["task"]
        self.assertEqual(completed["status"], "completed_on_time")

    def test_email_uses_tls_and_contains_login_password_and_role_path(self):
        from unittest.mock import MagicMock
        self.sender.stop()
        try:
            client = MagicMock()
            client.__enter__.return_value = client
            with patch.dict("os.environ", {"SMTP_HOST": "smtp.example.com", "SMTP_FROM": "admin@example.com", "SMTP_SECURITY": "starttls", "SMTP_USER": "mailer", "SMTP_PASSWORD": "secret"}, clear=True), patch.object(staff.smtplib, "SMTP", return_value=client):
                staff.send_registration("a@example.com", "director", "temporary-password")
            client.starttls.assert_called_once()
            client.login.assert_called_once_with("mailer", "secret")
            msg = client.send_message.call_args.args[0]
            self.assertEqual(msg["To"], "a@example.com")
            text = msg.get_content()
            self.assertIn("/Director", text)
            self.assertIn("a@example.com", text)
            self.assertIn("temporary-password", text)
        finally:
            self.sender.start()

    def test_bruteforce_throttle(self):
        self.create("a@example.com", "associate")
        for _ in range(5):
            self.assertEqual(self.client.post("/api/staff/login", json={"email": "a@example.com", "role": "associate", "password": "wrong"}).status_code, 401)
        self.assertEqual(self.client.post("/api/staff/login", json={"email": "a@example.com", "role": "associate", "password": self.passwords["a@example.com"]}).status_code, 429)


if __name__ == "__main__":
    unittest.main()
