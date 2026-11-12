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
        self.sender = patch.object(staff, "send_registration", side_effect=lambda email, role, password, sender=None: self.passwords.update({email: password}))
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

    def test_delete_revokes_access_and_preserves_task_history(self):
        self.create("director@example.com", "director")
        user = self.create("deputy@example.com", "associate")
        director = self.ready("director@example.com", "director")
        deputy = self.ready("deputy@example.com", "associate")
        deadline = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        task = self.client.post("/api/staff/tasks", headers=director, json={"assignee_id": user["id"], "description": "Отчёт", "deadline": deadline}).json()["task"]
        url = "/api/admin/users/" + user["id"]
        self.assertEqual(self.client.delete(url, headers=director).status_code, 401)
        with patch.object(staff, "send_account_deleted", side_effect=RuntimeError("SMTP недоступен")):
            self.assertEqual(self.client.delete(url, headers=self.admin).status_code, 503)
        self.assertEqual(self.client.get("/api/staff/me", headers=deputy).status_code, 200)
        with patch.object(staff, "send_account_deleted") as sent:
            self.assertEqual(self.client.delete(url, headers=self.admin).status_code, 200)
            sent.assert_called_once_with("deputy@example.com", None)
            self.assertEqual(self.client.delete(url, headers=self.admin).status_code, 404)
            sent.assert_called_once()
        self.assertEqual(self.client.get("/api/staff/me", headers=deputy).status_code, 401)
        self.assertEqual(self.client.get("/api/staff/associates", headers=director).json()["users"], [])
        remaining = self.client.get("/api/staff/tasks", headers=director).json()["tasks"]
        self.assertEqual(remaining[0]["id"], task["id"])
        self.assertEqual(remaining[0]["assignee_email"], "Удалённый пользователь")
        new_user = self.create("deputy@example.com", "associate")
        self.assertNotEqual(new_user["id"], user["id"])
        new_session = self.ready("deputy@example.com", "associate")
        self.assertEqual(self.client.get("/api/staff/tasks", headers=new_session).json()["tasks"], [])
        with self.store.connect() as db:
            deleted = db.execute("SELECT email,password_hash FROM users WHERE id=?", (user["id"],)).fetchone()
            self.assertNotEqual(deleted["email"], "deputy@example.com")
            self.assertEqual(deleted["password_hash"], "")

    def test_deleted_director_is_anonymous_to_assignee(self):
        director_user = self.create("director@example.com", "director")
        deputy_user = self.create("deputy@example.com", "associate")
        director = self.ready("director@example.com", "director")
        deputy = self.ready("deputy@example.com", "associate")
        deadline = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        self.client.post("/api/staff/tasks", headers=director, json={"assignee_id": deputy_user["id"], "description": "Отчёт", "deadline": deadline})
        with patch.object(staff, "send_account_deleted"):
            self.assertEqual(self.client.delete("/api/admin/users/" + director_user["id"], headers=self.admin).status_code, 200)
        self.assertEqual(self.client.get("/api/staff/me", headers=director).status_code, 401)
        self.assertEqual(self.client.get("/api/staff/tasks", headers=deputy).json()["tasks"][0]["director_email"], "Удалённый пользователь")

    def test_deletion_email_text(self):
        with patch.object(staff, "send_mail") as send:
            staff.send_account_deleted("deputy@example.com")
        recipient, subject, body, sender = send.call_args.args
        self.assertIsNone(sender)
        self.assertEqual(recipient, "deputy@example.com")
        self.assertIn("удалена", subject)
        self.assertIn("удалил", body)
        self.assertNotIn("пароль", body.lower())

    def test_auto_smtp_settings_and_fallback(self):
        self.assertEqual(self.client.get("/api/admin/mail-settings").status_code, 401)
        self.assertEqual(self.client.put("/api/admin/mail-settings", json={"sender": "staff@yandex.ru"}).status_code, 401)
        with patch.dict("os.environ", {"SMTP_PASSWORD": "not-shown", "SMTP_HOST": "custom.example", "SMTP_FROM": "custom@example.com", "SMTP_SECURITY": "starttls", "SMTP_PORT": "587"}, clear=True):
            response = self.client.put("/api/admin/mail-settings", headers=self.admin, json={"sender": "School@Yandex.ru"})
            self.assertEqual(response.status_code, 200, response.text)
            config = response.json()
            self.assertEqual((config["sender"], config["host"], config["port"], config["security"]), ("school@yandex.ru", "smtp.yandex.ru", 465, "ssl"))
            self.assertTrue(config["password_configured"])
            self.assertNotIn("not-shown", response.text)
            self.assertEqual(self.store.sender(), "school@yandex.ru")
            self.assertEqual(self.client.put("/api/admin/mail-settings", headers=self.admin, json={"sender": "school@unknown.com"}).status_code, 422)
            self.assertEqual(self.store.sender(), "school@yandex.ru")
            self.assertEqual(self.client.put("/api/admin/mail-settings", headers=self.admin, json={"sender": "not-an-email"}).status_code, 422)
            fallback = self.client.put("/api/admin/mail-settings", headers=self.admin, json={"sender": None}).json()
            self.assertEqual(fallback["source"], "environment")
            self.assertEqual(fallback["host"], "custom.example")
            self.assertIsNone(self.store.sender())
        for address, host in [("a@gmail.com", "smtp.gmail.com"), ("a@mail.ru", "smtp.mail.ru"), ("a@ya.ru", "smtp.yandex.ru")]:
            self.assertEqual(staff.smtp_settings(address)["host"], host)

    def test_auto_smtp_used_for_registration_and_deletion(self):
        self.client.put("/api/admin/mail-settings", headers=self.admin, json={"sender": "sender@mail.ru"})
        self.sender.stop()
        try:
            with patch.dict("os.environ", {}, clear=True):
                failed = self.client.post("/api/admin/users", headers=self.admin, json={"email": "a@example.com", "role": "associate"})
            self.assertEqual(failed.status_code, 503)
            self.assertIn("SMTP_PASSWORD", failed.json()["detail"])
            self.assertEqual(self.client.get("/api/admin/users", headers=self.admin).json()["users"], [])
        finally:
            self.sender.start()
        user = self.create("a@example.com", "associate")
        with patch.object(staff, "send_account_deleted") as sent:
            self.assertEqual(self.client.delete("/api/admin/users/"+user["id"], headers=self.admin).status_code, 200)
            sent.assert_called_once_with("a@example.com", "sender@mail.ru")
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "SMTP_PASSWORD"):
                staff.send_mail("a@example.com", "Subject", "Body", "sender@mail.ru")
        from unittest.mock import MagicMock
        client = MagicMock()
        client.__enter__.return_value = client
        with patch.dict("os.environ", {"SMTP_PASSWORD": "app-password", "SMTP_HOST": "ignored", "SMTP_PORT": "123"}, clear=True), patch.object(staff.smtplib, "SMTP_SSL", return_value=client) as smtp:
            staff.send_mail("a@example.com", "Subject", "Body", "sender@mail.ru")
        self.assertEqual(smtp.call_args.args[:2], ("smtp.mail.ru", 465))
        client.login.assert_called_once_with("sender@mail.ru", "app-password")
        self.assertEqual(client.send_message.call_args.args[0]["From"], "sender@mail.ru")

    def test_password_reset_flow_revokes_sessions_and_is_one_use(self):
        user = self.create("reset@example.com", "associate")
        old_session = self.ready("reset@example.com", "associate")
        body = {"email": "reset@example.com", "role": "associate"}
        with patch.object(staff, "send_password_reset") as send:
            response = self.client.post("/api/staff/password-reset/request", json=body)
            self.assertEqual(response.status_code, 200)
            args = send.call_args.args
            self.assertEqual(args[0], "reset@example.com")
            code = args[2]
            self.assertNotIn(code, response.text)
            with self.store.connect() as db:
                row = db.execute("SELECT token_hash FROM password_resets WHERE user_id=?", (user["id"],)).fetchone()
                self.assertNotIn(code, row["token_hash"])
            self.client.post("/api/staff/password-reset/request", json=body)
            send.assert_called_once()  # Повторная отправка ограничена.
        unknown = self.client.post("/api/staff/password-reset/request", json={"email": "unknown@example.com", "role": "associate"})
        self.assertEqual(unknown.json(), response.json())
        confirm = body | {"code": code, "password": "новый пароль для восстановления"}
        self.assertEqual(self.client.post("/api/staff/password-reset/confirm", json=confirm | {"role": "director"}).status_code, 400)
        self.assertEqual(self.client.post("/api/staff/password-reset/confirm", json=confirm | {"code": "wrong"}).status_code, 400)
        self.assertEqual(self.client.post("/api/staff/password-reset/confirm", json=confirm).status_code, 200)
        self.assertEqual(self.client.post("/api/staff/password-reset/confirm", json=confirm).status_code, 400)
        self.assertEqual(self.client.get("/api/staff/me", headers=old_session).status_code, 401)
        login = self.client.post("/api/staff/login", json=body | {"password": confirm["password"]})
        self.assertEqual(login.status_code, 200)
        self.assertFalse(login.json()["must_change"])

    def test_reset_expiry_failure_and_attempt_limit(self):
        user = self.create("reset@example.com", "director")
        body = {"email": "reset@example.com", "role": "director"}
        with patch.object(staff, "send_password_reset", side_effect=RuntimeError("SMTP error")):
            response = self.client.post("/api/staff/password-reset/request", json=body)
            self.assertEqual(response.status_code, 200)
        with self.store.connect() as db:
            self.assertIsNone(db.execute("SELECT * FROM password_resets WHERE user_id=?", (user["id"],)).fetchone())
            db.execute("DELETE FROM reset_throttle")
        with patch.object(staff, "send_password_reset") as send:
            self.client.post("/api/staff/password-reset/request", json=body)
            code = send.call_args.args[2]
        confirm = body | {"code": code, "password": "a very strong new password"}
        with self.store.connect() as db:
            db.execute("UPDATE password_resets SET expires=0 WHERE user_id=?", (user["id"],))
        self.assertEqual(self.client.post("/api/staff/password-reset/confirm", json=confirm).status_code, 400)
        with self.store.connect() as db:
            db.execute("UPDATE password_resets SET expires=? WHERE user_id=?", (int(staff.time.time())+100, user["id"]))
        for _ in range(10):
            self.assertEqual(self.client.post("/api/staff/password-reset/confirm", json=confirm | {"code": "wrong"}).status_code, 400)
        self.assertEqual(self.client.post("/api/staff/password-reset/confirm", json=confirm).status_code, 400)

    def test_reset_code_revoked_on_deletion(self):
        user = self.create("reset@example.com", "associate")
        body = {"email": "reset@example.com", "role": "associate"}
        with patch.object(staff, "send_password_reset") as send:
            self.client.post("/api/staff/password-reset/request", json=body)
            code = send.call_args.args[2]
        with patch.object(staff, "send_account_deleted"):
            self.assertEqual(self.client.delete("/api/admin/users/" + user["id"], headers=self.admin).status_code, 200)
        self.assertEqual(self.client.post("/api/staff/password-reset/confirm", json=body | {"code": code, "password": "a very strong password"}).status_code, 400)

    def test_bruteforce_throttle(self):
        self.create("a@example.com", "associate")
        for _ in range(5):
            self.assertEqual(self.client.post("/api/staff/login", json={"email": "a@example.com", "role": "associate", "password": "wrong"}).status_code, 401)
        self.assertEqual(self.client.post("/api/staff/login", json={"email": "a@example.com", "role": "associate", "password": self.passwords["a@example.com"]}).status_code, 429)


if __name__ == "__main__":
    unittest.main()
