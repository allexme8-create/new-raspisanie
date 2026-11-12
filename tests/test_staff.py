from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import date, datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
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

    def test_profile_name_and_task_visibility(self):
        director = self.create("director@example.com", "director")
        associate = self.create("associate@example.com", "associate")
        login = self.login("associate@example.com", "associate", associate["password"])
        temporary = {"Authorization": "Bearer " + login.json()["token"]}
        self.assertEqual(self.client.put("/api/staff/profile", headers=temporary, json={"full_name": "Тест"}).status_code, 403)
        self.assertEqual(self.client.put("/api/staff/profile", json={"full_name": "Тест"}).status_code, 401)
        associate_headers, _ = self.ready("associate@example.com", "associate", associate["password"])
        director_headers, _ = self.ready("director@example.com", "director", director["password"])
        self.assertEqual(self.client.put("/api/staff/profile", headers=associate_headers, json={"full_name": "   "}).status_code, 422)
        self.assertEqual(self.client.put("/api/staff/profile", headers=associate_headers, json={"full_name": "x" * 201}).status_code, 422)
        result = self.client.put("/api/staff/profile", headers=associate_headers, json={"full_name": "  Иванов  Иван Иванович  "})
        self.assertEqual(result.json()["user"]["full_name"], "Иванов Иван Иванович")
        self.assertEqual(self.client.get("/api/staff/me", headers=associate_headers).json()["user"]["full_name"], "Иванов Иван Иванович")
        self.assertEqual(self.client.get("/api/staff/associates", headers=director_headers).json()["users"][0]["full_name"], "Иванов Иван Иванович")
        users = self.client.get("/api/admin/users", headers=self.admin).json()["users"]
        self.assertEqual(next(u for u in users if u["id"] == associate["user"]["id"])["full_name"], "Иванов Иван Иванович")
        task = self.client.post("/api/staff/tasks", headers=director_headers, json={"assignee_id": associate["user"]["id"], "description": "Задача", "deadline": (staff.now() + timedelta(days=1)).isoformat()})
        self.assertEqual(task.status_code, 201, task.text)
        self.assertEqual(task.json()["task"]["assignee_name"], "Иванов Иван Иванович")
        self.client.delete(f"/api/admin/users/{associate['user']['id']}", headers=self.admin)
        self.assertEqual(self.client.get("/api/staff/tasks", headers=director_headers).json()["tasks"][0]["assignee_name"], "Удалённый пользователь")
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT full_name FROM users WHERE id=?", (associate["user"]["id"],)).fetchone()[0], "")

    def test_admin_can_set_name_at_creation(self):
        created = self.client.post("/api/admin/users", headers=self.admin, json={"email":"named@example.com", "role":"teacher", "full_name":"  Иванова  Анна Ивановна  ", "position":"Учитель"})
        self.assertEqual(created.status_code, 201, created.text)
        user = created.json()["user"]
        self.assertEqual(user["full_name"], "Иванова Анна Ивановна")
        self.assertEqual(self.client.get("/api/admin/users", headers=self.admin).json()["users"][0]["full_name"], user["full_name"])
        headers, _ = self.ready("named@example.com", "teacher", created.json()["password"])
        self.assertEqual(self.client.get("/api/staff/me", headers=headers).json()["user"]["full_name"], user["full_name"])
        self.assertEqual(self.client.put("/api/staff/profile", headers=headers, json={"full_name":"Новое ФИО"}).json()["user"]["full_name"], "Новое ФИО")
        self.assertEqual(self.client.post("/api/admin/users", headers=self.admin, json={"email":"long@example.com", "role":"teacher", "full_name":"x"*201}).status_code, 422)
        blank = self.client.post("/api/admin/users", headers=self.admin, json={"email":"blank@example.com", "role":"teacher", "full_name":"   "})
        self.assertEqual(blank.status_code, 201)
        self.assertEqual(blank.json()["user"]["full_name"], "")

    def test_positions_create_update_and_tasks(self):
        director = self.create("dir@example.com", "director")
        created = self.client.post("/api/admin/users", headers=self.admin, json={"email":"teach@example.com", "role":"teacher", "position":"  Учитель   начальных классов  "})
        self.assertEqual(created.status_code, 201, created.text)
        teacher = created.json()
        self.assertEqual(teacher["user"]["position"], "Учитель начальных классов")
        dh, _ = self.ready("dir@example.com", "director", director["password"])
        th, _ = self.ready("teach@example.com", "teacher", teacher["password"])
        self.client.put("/api/staff/profile", headers=dh, json={"full_name":"Директор", "position":"Директор школы"})
        self.client.put("/api/staff/profile", headers=th, json={"full_name":"Иванова"})
        self.assertEqual(self.client.get("/api/staff/me", headers=th).json()["user"]["position"], "Учитель начальных классов")
        self.assertEqual(self.client.get("/api/staff/assignees", headers=dh).json()["users"][0]["position"], "Учитель начальных классов")
        self.assertEqual(self.client.put("/api/staff/profile", headers=th, json={"full_name":"Иванова", "position":"x"*201}).status_code, 422)
        body={"assignee_id":teacher["user"]["id"],"description":"Задача", "deadline":(staff.now()+timedelta(days=1)).isoformat()}
        task=self.client.post("/api/staff/tasks",headers=dh,json=body).json()["task"]
        self.assertEqual(task["assignee_position"], "Учитель начальных классов")
        self.assertEqual(task["director_position"], "Директор школы")
        self.client.put("/api/staff/profile", headers=th, json={"full_name":"Иванова", "position":" Учитель математики "})
        self.assertEqual(self.client.get("/api/staff/tasks", headers=dh).json()["tasks"][0]["assignee_position"], "Учитель математики")
        self.client.put("/api/staff/profile", headers=th, json={"full_name":"Иванова", "position":""})
        self.assertEqual(self.client.get("/api/staff/tasks", headers=dh).json()["tasks"][0]["assignee_position"], "Учитель")
        self.client.delete("/api/admin/users/"+teacher["user"]["id"], headers=self.admin)
        self.assertEqual(self.client.get("/api/staff/tasks", headers=dh).json()["tasks"][0]["assignee_position"], "")
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT position FROM users WHERE id=?", (teacher["user"]["id"],)).fetchone()[0], "")

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
            self.assertEqual(db.execute("SELECT position FROM users WHERE id='u'").fetchone()[0], "")
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='mail_oauth'").fetchone())
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='password_resets'").fetchone())

    def test_tasks_permissions_and_deletion(self):
        director_data = self.create("director@example.com", "director")
        deputy_data = self.create("deputy@example.com", "associate")
        director, _ = self.ready("director@example.com", "director", director_data["password"])
        deputy, _ = self.ready("deputy@example.com", "associate", deputy_data["password"])
        self.assertEqual(self.client.get("/api/staff/associates", headers=deputy).status_code, 403)
        body = {"assignee_id": deputy_data["user"]["id"], "description": "Отчёт", "deadline": (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}
        self.assertEqual(self.client.post("/api/staff/tasks", headers=deputy, json=body).status_code, 422)
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

    def test_teacher_projects_permissions_and_progress(self):
        d = self.create("d@example.com", "director")
        a = self.create("a@example.com", "associate")
        b = self.create("b@example.com", "associate")
        t = self.create("t@example.com", "teacher")
        t2 = self.create("t2@example.com", "teacher")
        dh, _ = self.ready("d@example.com", "director", d["password"])
        ah, _ = self.ready("a@example.com", "associate", a["password"])
        bh, _ = self.ready("b@example.com", "associate", b["password"])
        th, _ = self.ready("t@example.com", "teacher", t["password"])
        th2, _ = self.ready("t2@example.com", "teacher", t2["password"])
        for headers, name in [(dh, "Директор"), (ah, "Заместитель"), (th, "Учитель")]:
            self.client.put("/api/staff/profile", headers=headers, json={"full_name": name})
        self.assertEqual(self.client.post("/api/staff/projects", headers=th, json={"title":"Проект"}).status_code, 403)
        self.assertEqual(self.client.post("/api/staff/projects", headers=ah, json={"title":"  "}).status_code, 422)
        project = self.client.post("/api/staff/projects", headers=ah, json={"title":"Проект А"}).json()["id"]
        taskbody = {"assignee_id":t["user"]["id"], "description":"Работа", "deadline":(staff.now()+timedelta(days=1)).isoformat(), "project_id":project}
        self.assertEqual(self.client.post("/api/staff/tasks", headers=th, json=taskbody).status_code, 403)
        self.assertEqual(self.client.post("/api/staff/tasks", headers=bh, json=taskbody).status_code, 403)
        self.assertEqual(self.client.post("/api/staff/tasks", headers=ah, json=taskbody | {"assignee_id":b["user"]["id"]}).status_code, 422)
        task = self.client.post("/api/staff/tasks", headers=ah, json=taskbody).json()["task"]
        self.assertEqual(self.client.post("/api/staff/tasks", headers=dh, json=taskbody | {"assignee_id":a["user"]["id"]}).status_code, 201)
        self.assertEqual(len(self.client.get("/api/staff/tasks", headers=dh).json()["tasks"]), 2)
        self.assertEqual(len(self.client.get("/api/staff/tasks", headers=ah).json()["tasks"]), 2)
        self.assertEqual(len(self.client.get("/api/staff/tasks", headers=th).json()["tasks"]), 1)
        self.assertEqual(self.client.get("/api/staff/projects", headers=th2).json()["projects"], [])
        self.assertEqual(self.client.get("/api/staff/tasks", headers=bh).json()["tasks"], [])
        url = f"/api/staff/tasks/{task['id']}/completion"
        self.assertEqual(self.client.put(url, headers=th2, json={"completed": True}).status_code, 404)
        self.assertEqual(self.client.put(url, headers=th, json={"completed": True}).status_code, 200)
        observed = self.client.get("/api/staff/tasks", headers=dh).json()["tasks"]
        self.assertEqual(next(item for item in observed if item["id"] == task["id"])["status"], "completed_on_time")
        self.assertEqual(self.client.get("/api/staff/projects", headers=dh).json()["projects"][0]["title"], "Проект А")
        self.assertEqual(self.client.post("/api/staff/tasks", headers=ah, json=taskbody | {"project_id":None}).status_code, 201)

    def test_role_migration_preserves_references(self):
        created = self.create("d@example.com", "director")
        associate = self.create("a@example.com", "associate")
        dh, _ = self.ready("d@example.com", "director", created["password"])
        self.client.post("/api/staff/tasks", headers=dh, json={"assignee_id":associate["user"]["id"], "description":"Сохранить", "deadline":(staff.now()+timedelta(days=1)).isoformat()})
        # Simulate the previous role constraint, keeping the real child tables.
        with self.store.connect() as db:
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("PRAGMA writable_schema=ON")
            db.execute("UPDATE sqlite_master SET sql=replace(sql, \",'teacher'\", '') WHERE name='users'")
            db.execute("PRAGMA writable_schema=OFF")
        self.store.init()
        self.assertEqual(len(self.client.get("/api/staff/tasks", headers=dh).json()["tasks"]), 1)
        self.assertEqual(self.create("teacher@example.com", "teacher")["user"]["role"], "teacher")
        with self.store.connect() as db:
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_task_progress_and_comment_permissions(self):
        director = self.create("dir@example.com", "director")
        deputy = self.create("dep@example.com", "associate")
        teacher = self.create("teacher@example.com", "teacher")
        other = self.create("other@example.com", "teacher")
        dh, _ = self.ready("dir@example.com", "director", director["password"])
        ah, _ = self.ready("dep@example.com", "associate", deputy["password"])
        th, _ = self.ready("teacher@example.com", "teacher", teacher["password"])
        oh, _ = self.ready("other@example.com", "teacher", other["password"])
        self.client.put("/api/staff/profile", headers=th, json={"full_name":"Учитель", "position":"Учитель музыки"})
        project = self.client.post("/api/staff/projects", headers=ah, json={"title":"Проект"}).json()["id"]
        body = {"assignee_id":teacher["user"]["id"], "description":"Тест", "deadline":(staff.now()+timedelta(days=1)).isoformat(), "project_id":project}
        task = self.client.post("/api/staff/tasks", headers=ah, json=body).json()["task"]
        base = f"/api/staff/tasks/{task['id']}"
        self.assertFalse(task["partial"])
        self.assertEqual(task["failure_reason"], "")
        self.assertEqual(self.client.put(base+"/progress", headers=ah, json={"partial":True,"reason":"Причина"}).status_code, 404)
        self.assertEqual(self.client.put(base+"/progress", headers=oh, json={"partial":True,"reason":"Причина"}).status_code, 404)
        self.assertEqual(self.client.put(base+"/progress", headers=th, json={"partial":True,"reason":"x"*2001}).status_code, 422)
        result=self.client.put(base+"/progress", headers=th, json={"partial":True,"reason":"  Ждём данные  "})
        self.assertTrue(result.json()["task"]["partial"])
        self.assertEqual(result.json()["task"]["failure_reason"],"Ждём данные")
        self.assertTrue(self.client.get("/api/staff/tasks", headers=dh).json()["tasks"][0]["partial"])
        self.assertEqual(self.client.get(base+"/comments",headers=oh).status_code, 404)
        self.assertEqual(self.client.post(base+"/comments",headers=oh,json={"text":"чужой"}).status_code, 404)
        self.assertEqual(self.client.get(base+"/comments").status_code, 401)
        self.assertEqual(self.client.post(base+"/comments",headers=th,json={"text":"  "}).status_code, 422)
        self.assertEqual(self.client.post(base+"/comments",headers=th,json={"text":"x"*2001}).status_code, 422)
        self.assertEqual(self.client.post(base+"/comments",headers=th,json={"text":"  Начала работу  "}).status_code, 201)
        self.assertEqual(self.client.post(base+"/comments",headers=dh,json={"text":"Спасибо"}).status_code, 201)
        comments=self.client.get(base+"/comments",headers=ah).json()["comments"]
        self.assertEqual([c["text"] for c in comments], ["Начала работу", "Спасибо"])
        self.assertEqual(comments[0]["author_position"], "Учитель музыки")
        completed=self.client.put(base+"/completion",headers=th,json={"completed":True}).json()["task"]
        self.assertFalse(completed["partial"])
        self.assertEqual(completed["failure_reason"], "Ждём данные")
        self.assertEqual(self.client.put(base+"/progress",headers=th,json={"partial":True,"reason":""}).status_code, 409)
        self.assertEqual(self.client.post(base+"/comments",headers=th,json={"text":"Выполнено"}).status_code, 201)
        self.client.delete("/api/admin/users/"+teacher["user"]["id"],headers=self.admin)
        comments=self.client.get(base+"/comments",headers=dh).json()["comments"]
        self.assertEqual(comments[0]["author_name"],"Удалённый пользователь")
        self.assertEqual(comments[0]["author_position"],"")
        self.store.init()
        self.assertEqual(len(self.client.get(base+"/comments",headers=dh).json()["comments"]),3)

    def test_collaborators_task_visibility_and_history(self):
        director = self.create("dir@example.com", "director")
        deputy = self.create("dep@example.com", "associate")
        teacher = self.create("teacher@example.com", "teacher")
        helper = self.create("helper@example.com", "teacher")
        stranger = self.create("stranger@example.com", "teacher")
        dh, _ = self.ready("dir@example.com", "director", director["password"])
        ah, _ = self.ready("dep@example.com", "associate", deputy["password"])
        th, _ = self.ready("teacher@example.com", "teacher", teacher["password"])
        hh, _ = self.ready("helper@example.com", "teacher", helper["password"])
        sh, _ = self.ready("stranger@example.com", "teacher", stranger["password"])
        self.client.put("/api/staff/profile", headers=hh, json={"full_name":"Помощник", "position":"Учитель истории"})
        project = self.client.post("/api/staff/projects", headers=ah, json={"title":"Проект"}).json()["id"]
        body={"assignee_id":teacher["user"]["id"], "description":"Первый", "deadline":(staff.now()+timedelta(days=1)).isoformat(), "project_id":project}
        task = self.client.post("/api/staff/tasks",headers=ah,json=body).json()["task"]
        second = self.client.post("/api/staff/tasks",headers=ah,json=body | {"description":"Не для помощника"}).json()["task"]
        base=f"/api/staff/tasks/{task['id']}"
        self.client.post(base+"/comments",headers=th,json={"text":"Ранее сделано"})
        self.client.put(base+"/progress",headers=th,json={"partial":True,"reason":"Нет данных"})
        self.client.put(base+"/progress",headers=th,json={"partial":True,"reason":"Данные получены"})
        invite=base+"/collaborators"
        self.assertEqual(self.client.get(invite+"/candidates",headers=th).status_code,404)
        self.assertEqual(self.client.post(invite,headers=dh,json={"user_id":helper["user"]["id"]}).status_code,404)
        self.assertEqual(self.client.post(invite,headers=th,json={"user_id":helper["user"]["id"]}).status_code,404)
        self.assertEqual(self.client.post(invite,headers=ah,json={"user_id":teacher["user"]["id"]}).status_code,422)
        self.assertEqual(self.client.post(invite,headers=ah,json={"user_id":"unknown"}).status_code,422)
        candidates=self.client.get(invite+"/candidates",headers=ah).json()["users"]
        self.assertIn(helper["user"]["id"],[u["id"] for u in candidates])
        self.assertTrue(all("email" not in u for u in candidates))
        self.assertEqual(self.client.post(invite,headers=ah,json={"user_id":helper["user"]["id"]}).status_code,201)
        self.assertEqual(self.client.post(invite,headers=ah,json={"user_id":helper["user"]["id"]}).status_code,409)
        tasks=self.client.get("/api/staff/tasks",headers=hh).json()["tasks"]
        self.assertEqual([t["id"] for t in tasks],[task["id"]])
        self.assertEqual(tasks[0]["collaborators"][0]["full_name"],"Помощник")
        self.assertEqual(len(self.client.get("/api/staff/projects",headers=hh).json()["projects"]),1)
        history=self.client.get(base+"/comments",headers=hh).json()
        self.assertEqual(history["comments"][0]["text"],"Ранее сделано")
        self.assertTrue(any("Нет данных" in event["text"] for event in history["events"]))
        self.assertTrue(any("Данные получены" in event["text"] for event in history["events"]))
        self.assertEqual(self.client.get(f"/api/staff/tasks/{second['id']}/comments",headers=hh).status_code,404)
        self.assertEqual(self.client.post(base+"/comments",headers=hh,json={"text":"Помогаю"}).status_code,201)
        self.assertEqual(self.client.put(base+"/completion",headers=hh,json={"completed":True}).status_code,404)
        self.assertEqual(self.client.put(base+"/progress",headers=hh,json={"partial":True}).status_code,404)
        self.assertEqual(self.client.get(base+"/comments",headers=sh).status_code,404)
        self.assertEqual(self.client.put(base+"/completion",headers=th,json={"completed":True}).status_code,200)
        self.assertEqual(self.client.post(invite,headers=ah,json={"user_id":stranger["user"]["id"]}).status_code,409)
        self.assertTrue(any(e["text"]=="Задача выполнена" for e in self.client.get(base+"/comments",headers=hh).json()["events"]))
        self.assertEqual(self.client.get(base+"/comments",headers=hh).status_code,200)
        # Standalone task also appears for an invited user.
        standalone=self.client.post("/api/staff/tasks",headers=ah,json=body | {"project_id":None}).json()["task"]
        self.assertEqual(self.client.post(f"/api/staff/tasks/{standalone['id']}/collaborators",headers=ah,json={"user_id":helper["user"]["id"]}).status_code,201)
        self.assertEqual(len(self.client.get("/api/staff/tasks",headers=hh).json()["tasks"]),2)
        self.client.delete("/api/admin/users/"+helper["user"]["id"],headers=self.admin)
        rows=self.client.get("/api/staff/tasks",headers=ah).json()["tasks"]
        self.assertEqual(next(t for t in rows if t["id"]==task["id"])["collaborators"][0]["full_name"],"Удалённый пользователь")
        self.assertEqual(self.client.get(base+"/comments",headers=hh).status_code,401)

    def test_initiator_notifications_and_read_watermark(self):
        director = self.create("d@example.com", "director")
        deputy = self.create("a@example.com", "associate")
        teacher = self.create("t@example.com", "teacher")
        helper = self.create("h@example.com", "teacher")
        dh, _ = self.ready("d@example.com", "director", director["password"])
        ah, _ = self.ready("a@example.com", "associate", deputy["password"])
        th, _ = self.ready("t@example.com", "teacher", teacher["password"])
        hh, _ = self.ready("h@example.com", "teacher", helper["password"])
        self.client.put("/api/staff/profile", headers=th, json={"full_name":"Учитель", "position":"Учитель математики"})
        project = self.client.post("/api/staff/projects", headers=ah, json={"title":"Проект"}).json()["id"]
        body={"assignee_id":teacher["user"]["id"], "description":"Задача", "deadline":(staff.now()+timedelta(days=1)).isoformat(), "project_id":project}
        task=self.client.post("/api/staff/tasks",headers=ah,json=body).json()["task"]
        url=f"/api/staff/tasks/{task['id']}"
        self.client.post(url+"/collaborators",headers=ah,json={"user_id":helper["user"]["id"]})
        self.assertEqual(self.client.get("/api/staff/notifications").status_code,401)
        self.client.post(url+"/comments",headers=ah,json={"text":"Автор"})
        self.assertEqual(self.client.get("/api/staff/notifications",headers=ah).json()["notifications"],[])
        assignee_notifications = self.client.get("/api/staff/notifications",headers=th).json()["notifications"]
        self.assertEqual(len(assignee_notifications),1)
        self.assertEqual(assignee_notifications[0]["kind"],"comment")
        self.assertEqual(assignee_notifications[0]["task_id"],task["id"])
        seen = self.client.get(url+"/comments",headers=th).json()["notification_through_id"]
        self.client.post(url+"/notifications/read",headers=th,json={"through_id":seen})
        self.client.post(url+"/comments",headers=th,json={"text":"Выполняю"})
        first=self.client.get("/api/staff/notifications",headers=ah).json()["notifications"]
        self.assertEqual(len(first),1)
        self.assertEqual(first[0]["kind"],"comment")
        self.assertEqual(first[0]["project_id"],project)
        self.assertEqual(first[0]["actor_name"],"Учитель")
        self.assertEqual(first[0]["actor_position"],"Учитель математики")
        self.assertEqual(self.client.get("/api/staff/notifications",headers=dh).json()["notifications"],[])
        self.assertEqual(self.client.get("/api/staff/notifications",headers=th).json()["notifications"],[])
        snapshot=self.client.get(url+"/comments",headers=ah).json()["notification_through_id"]
        self.client.post(url+"/comments",headers=hh,json={"text":"Помогаю"})
        helper_notice = self.client.get("/api/staff/notifications",headers=th).json()["notifications"]
        self.assertEqual(len(helper_notice),1)
        self.assertEqual(helper_notice[0]["kind"],"comment")
        self.assertEqual(self.client.get("/api/staff/notifications",headers=hh).json()["notifications"],[])
        self.client.post(url+"/notifications/read",headers=th,json={"through_id":snapshot})
        self.assertEqual(len(self.client.get("/api/staff/notifications",headers=ah).json()["notifications"]),2)
        self.client.post(url+"/notifications/read",headers=ah,json={"through_id":snapshot})
        remaining=self.client.get("/api/staff/notifications",headers=ah).json()["notifications"]
        self.assertEqual(len(remaining),1)
        self.assertGreater(remaining[0]["id"],snapshot)
        self.client.put(url+"/completion",headers=th,json={"completed":True})
        self.client.put(url+"/completion",headers=th,json={"completed":True})
        remaining=self.client.get("/api/staff/notifications",headers=ah).json()["notifications"]
        self.assertEqual([n["kind"] for n in remaining].count("completed"),1)
        latest=self.client.get(url+"/comments",headers=ah).json()["notification_through_id"]
        self.client.post(url+"/notifications/read",headers=ah,json={"through_id":latest})
        self.assertEqual(self.client.get("/api/staff/notifications",headers=ah).json()["notifications"],[])
        self.store.init()
        self.assertEqual(self.client.get("/api/staff/notifications",headers=ah).json()["notifications"],[])
        self.client.post(url+"/comments",headers=th,json={"text":"Ещё"})
        self.assertEqual(len(self.client.get("/api/staff/notifications",headers=ah).json()["notifications"]),1)

    def test_assignee_comment_notifications_for_standalone_task(self):
        director=self.create("director2@example.com", "director")
        teacher=self.create("teacher2@example.com", "teacher")
        dh,_=self.ready("director2@example.com", "director", director["password"])
        th,_=self.ready("teacher2@example.com", "teacher", teacher["password"])
        body={"assignee_id":teacher["user"]["id"], "description":"Обычная задача", "deadline":(staff.now()+timedelta(days=1)).isoformat()}
        task=self.client.post("/api/staff/tasks",headers=dh,json=body).json()["task"]
        url=f"/api/staff/tasks/{task['id']}"
        self.client.post(url+"/comments",headers=dh,json={"text":"Комментарий руководителя"})
        self.client.post(url+"/comments",headers=th,json={"text":"Ответ"})
        director_notice=self.client.get("/api/staff/notifications",headers=dh).json()["notifications"]
        teacher_notice=self.client.get("/api/staff/notifications",headers=th).json()["notifications"]
        self.assertEqual(len(director_notice),1)
        self.assertEqual(len(teacher_notice),1)
        self.assertIsNone(teacher_notice[0]["project_id"])
        snapshot=self.client.get(url+"/comments",headers=th).json()["notification_through_id"]
        self.client.post(url+"/comments",headers=dh,json={"text":"Новое после просмотра"})
        self.client.post(url+"/notifications/read",headers=th,json={"through_id":snapshot})
        self.assertEqual(len(self.client.get("/api/staff/notifications",headers=th).json()["notifications"]),1)
        self.assertEqual(len(self.client.get("/api/staff/notifications",headers=dh).json()["notifications"]),1)
        self.store.init()
        self.assertEqual(len(self.client.get("/api/staff/notifications",headers=th).json()["notifications"]),1)

    def test_initiator_can_return_completed_task_for_rework(self):
        director=self.create("d-rework@example.com", "director")
        associate=self.create("a-rework@example.com", "associate")
        teacher=self.create("t-rework@example.com", "teacher")
        other=self.create("other-rework@example.com", "teacher")
        dh,_=self.ready("d-rework@example.com", "director", director["password"])
        ah,_=self.ready("a-rework@example.com", "associate", associate["password"])
        th,_=self.ready("t-rework@example.com", "teacher", teacher["password"])
        oh,_=self.ready("other-rework@example.com", "teacher", other["password"])
        project=self.client.post("/api/staff/projects",headers=ah,json={"title":"Проект"}).json()["id"]
        body={"assignee_id":teacher["user"]["id"], "description":"Отчёт", "deadline":(staff.now()+timedelta(days=1)).isoformat(), "project_id":project}
        task=self.client.post("/api/staff/tasks",headers=ah,json=body).json()["task"]
        url=f"/api/staff/tasks/{task['id']}"
        new_deadline=(staff.now()+timedelta(days=2)).isoformat()
        payload={"comment":"Нужно дополнить", "deadline":new_deadline, "expected_completed_at":"2020-01-01T00:00:00+00:00"}
        self.assertEqual(self.client.post(url+"/rework",headers=ah,json=payload).status_code,409)
        done=self.client.put(url+"/completion",headers=th,json={"completed":True,"cycle":0}).json()["task"]
        payload["expected_completed_at"]=done["completed_at"]
        for headers in (dh,th,oh):
            self.assertEqual(self.client.post(url+"/rework",headers=headers,json=payload).status_code,404)
        self.assertEqual(self.client.post(url+"/rework",headers=ah,json=payload | {"comment":"   "}).status_code,422)
        self.assertEqual(self.client.post(url+"/rework",headers=ah,json=payload | {"deadline":(staff.now()-timedelta(days=1)).isoformat()}).status_code,422)
        self.assertEqual(self.client.post(url+"/rework",headers=ah,json=payload | {"deadline":"2030-01-01T12:00:00"}).status_code,422)
        returned=self.client.post(url+"/rework",headers=ah,json=payload)
        self.assertEqual(returned.status_code,200,returned.text)
        updated=returned.json()["task"]
        self.assertEqual(updated["deadline"],new_deadline)
        self.assertIsNone(updated["completed_at"])
        self.assertTrue(updated["rework"])
        self.assertEqual(updated["cycle"],1)
        self.assertEqual(self.client.post(url+"/rework",headers=ah,json=payload).status_code,409)
        history=self.client.get(url+"/comments",headers=th).json()["events"]
        self.assertTrue(any("Задача выполнена"==event["text"] for event in history))
        self.assertTrue(any("Нужно дополнить" in event["text"] and done["completed_at"] in event["text"] for event in history))
        self.assertTrue(any(n["kind"]=="rework" for n in self.client.get("/api/staff/notifications",headers=th).json()["notifications"]))
        self.assertEqual(self.client.put(url+"/completion",headers=th,json={"completed":True,"cycle":0}).status_code,409)
        again=self.client.put(url+"/completion",headers=th,json={"completed":True,"cycle":1}).json()["task"]
        self.assertFalse(again["rework"])
        self.assertEqual(self.client.post(url+"/rework",headers=ah,json=payload).status_code,409)
        payload["expected_completed_at"]=again["completed_at"]
        self.assertEqual(self.client.post(url+"/rework",headers=ah,json=payload).json()["task"]["cycle"],2)
        self.assertEqual(self.client.put(url+"/completion",headers=th,json={"completed":True}).status_code,409)
        self.store.init()
        self.assertEqual(self.client.get("/api/staff/tasks",headers=th).json()["tasks"][0]["cycle"],2)

    def test_final_approval_personal_deletion_and_project_completion(self):
        director=self.create("d-final@example.com", "director")
        deputy=self.create("a-final@example.com", "associate")
        teacher=self.create("t-final@example.com", "teacher")
        helper=self.create("h-final@example.com", "teacher")
        dh,_=self.ready("d-final@example.com", "director", director["password"])
        ah,_=self.ready("a-final@example.com", "associate", deputy["password"])
        th,_=self.ready("t-final@example.com", "teacher", teacher["password"])
        hh,_=self.ready("h-final@example.com", "teacher", helper["password"])
        project=self.client.post("/api/staff/projects",headers=ah,json={"title":"Проект"}).json()["id"]
        body={"assignee_id":teacher["user"]["id"],"description":"Работа", "deadline":(staff.now()+timedelta(days=1)).isoformat(),"project_id":project}
        task=self.client.post("/api/staff/tasks",headers=ah,json=body).json()["task"]
        url=f"/api/staff/tasks/{task['id']}"
        self.client.post(url+"/collaborators",headers=ah,json={"user_id":helper["user"]["id"]})
        self.assertEqual(self.client.post(url+"/hide",headers=th).status_code,409)
        self.assertEqual(self.client.post(url+"/hide",headers=hh).status_code,409)
        self.assertEqual(self.client.post(url+"/hide",headers=dh).status_code,404)
        self.assertEqual(self.client.post(f"/api/staff/projects/{project}/complete",headers=dh).status_code,404)
        self.assertEqual(self.client.post(f"/api/staff/projects/{project}/complete",headers=ah).status_code,409)
        # The author may remove their copy even before approval, without affecting others.
        self.assertEqual(self.client.post(url+"/hide",headers=ah).status_code,200)
        self.assertEqual(self.client.get("/api/staff/tasks",headers=ah).json()["tasks"],[])
        archived=self.client.get("/api/staff/tasks?include_hidden=true",headers=ah).json()["tasks"]
        self.assertTrue(archived[0]["hidden"])
        self.assertEqual(len(self.client.get("/api/staff/tasks",headers=th).json()["tasks"]),1)
        proj=self.client.get("/api/staff/projects",headers=ah).json()["projects"][0]
        self.assertEqual((proj["total_tasks"],proj["approved_tasks"]),(1,0))
        complete=self.client.put(url+"/completion",headers=th,json={"completed":True}).json()["task"]
        payload={"expected_completed_at":complete["completed_at"]}
        self.assertEqual(self.client.post(url+"/hide",headers=th).status_code,409)
        self.assertEqual(self.client.post(url+"/approve",headers=dh,json=payload).status_code,404)
        self.assertEqual(self.client.post(url+"/approve",headers=th,json=payload).status_code,404)
        self.assertEqual(self.client.post(url+"/approve",headers=ah,json={"expected_completed_at":"wrong"}).status_code,409)
        approval=self.client.post(url+"/approve",headers=ah,json=payload)
        self.assertEqual(approval.status_code,200,approval.text)
        self.assertTrue(approval.json()["task"]["approved_at"])
        self.assertEqual(self.client.post(url+"/approve",headers=ah,json=payload).status_code,409)
        self.assertEqual(self.client.post(url+"/rework",headers=ah,json={"comment":"доделать", "deadline":(staff.now()+timedelta(days=2)).isoformat(), **payload}).status_code,409)
        for headers in (th,hh):
            self.assertTrue(any(n["kind"]=="approved" for n in self.client.get("/api/staff/notifications",headers=headers).json()["notifications"]))
        self.assertEqual(self.client.post(url+"/hide",headers=th).status_code,200)
        self.assertEqual(self.client.get("/api/staff/tasks",headers=th).json()["tasks"],[])
        self.assertEqual(len(self.client.get("/api/staff/tasks",headers=hh).json()["tasks"]),1)
        self.assertEqual(len(self.client.get("/api/staff/tasks",headers=dh).json()["tasks"]),1)
        self.assertEqual(self.client.post(url+"/restore",headers=th).status_code,200)
        self.assertEqual(len(self.client.get("/api/staff/tasks",headers=th).json()["tasks"]),1)
        self.assertEqual(self.client.post(f"/api/staff/projects/{project}/complete",headers=ah).status_code,200)
        self.assertTrue(self.client.get("/api/staff/projects",headers=dh).json()["projects"][0]["finished_at"])
        self.assertEqual(self.client.post("/api/staff/tasks",headers=ah,json=body).status_code,409)
        self.assertEqual(self.client.post(f"/api/staff/projects/{project}/complete",headers=ah).status_code,409)
        self.assertTrue(any("выполнено полностью" in e["text"] for e in self.client.get(url+"/comments",headers=hh).json()["events"]))
        self.store.init()
        self.assertEqual(self.client.get("/api/staff/tasks",headers=ah).json()["tasks"],[])
        self.assertEqual(self.client.post(url+"/restore",headers=ah).status_code,200)
        self.assertEqual(len(self.client.get("/api/staff/tasks",headers=ah).json()["tasks"]),1)

    def test_assignee_can_undo_completion_before_final_approval(self):
        director=self.create("undo-d@example.com", "director")
        teacher=self.create("undo-t@example.com", "teacher")
        other=self.create("undo-o@example.com", "teacher")
        dh,_=self.ready("undo-d@example.com", "director", director["password"])
        th,_=self.ready("undo-t@example.com", "teacher", teacher["password"])
        oh,_=self.ready("undo-o@example.com", "teacher", other["password"])
        body={"assignee_id":teacher["user"]["id"], "description":"Проверить", "deadline":(staff.now()+timedelta(days=1)).isoformat()}
        task=self.client.post("/api/staff/tasks",headers=dh,json=body).json()["task"]
        url=f"/api/staff/tasks/{task['id']}"
        complete=self.client.put(url+"/completion",headers=th,json={"completed":True,"cycle":0}).json()["task"]
        undo={"completed":False,"cycle":0,"expected_completed_at":complete["completed_at"]}
        self.assertEqual(self.client.put(url+"/completion",headers=dh,json=undo).status_code,404)
        self.assertEqual(self.client.put(url+"/completion",headers=oh,json=undo).status_code,404)
        self.assertEqual(self.client.put(url+"/completion",headers=th,json=undo | {"expected_completed_at":"wrong"}).status_code,409)
        self.assertEqual(self.client.put(url+"/completion",headers=th,json={"completed":False}).status_code,400)
        response=self.client.put(url+"/completion",headers=th,json=undo)
        self.assertEqual(response.status_code,200,response.text)
        self.assertIsNone(response.json()["task"]["completed_at"])
        self.assertEqual(response.json()["task"]["cycle"],1)
        self.assertEqual(response.json()["task"]["status"],"pending")
        self.assertEqual(self.client.put(url+"/completion",headers=th,json=undo).status_code,409)
        self.assertEqual(self.client.put(url+"/completion",headers=th,json={"completed":True,"cycle":0}).status_code,409)
        self.assertEqual(self.client.post(url+"/approve",headers=dh,json={"expected_completed_at":complete["completed_at"]}).status_code,409)
        notifications=self.client.get("/api/staff/notifications",headers=dh).json()["notifications"]
        self.assertEqual([n["kind"] for n in notifications], ["completion_undone","completed"])
        history=self.client.get(url+"/comments",headers=th).json()["events"]
        self.assertFalse(any("снял отметку" in e["text"] or e["text"] == "Задача выполнена" for e in history))
        again=self.client.put(url+"/completion",headers=th,json={"completed":True,"cycle":1}).json()["task"]
        self.assertEqual(self.client.put(url+"/completion",headers=th,json=undo | {"cycle":1}).status_code,409)
        self.client.post(url+"/approve",headers=dh,json={"expected_completed_at":again["completed_at"]})
        self.assertEqual(self.client.put(url+"/completion",headers=th,json={"completed":False,"cycle":1,"expected_completed_at":again["completed_at"]}).status_code,409)
        self.assertIsNotNone(self.client.get("/api/staff/tasks",headers=th).json()["tasks"][0]["approved_at"])
        history=self.client.get(url+"/comments",headers=th).json()["events"]
        self.assertEqual(sum(e["text"] == "Задача выполнена" for e in history),1)
        self.assertFalse(any("снял отметку" in e["text"] for e in history))

    def test_hidden_accidental_completion_keeps_previous_rework_history(self):
        events = [{"id":str(i),"text":text} for i,text in enumerate([
            "Задача создана", "Задача выполнена", "Возвращено на доработку. Причина: исправить",
            "Исполнитель снял отметку выполнения (отмечено ранее: старый импорт)",
            "Задача выполнена", "Исполнитель снял отметку выполнения (отмечено ранее: сейчас)",
            "Задача выполнена", "Инициатор подтвердил: выполнено полностью"])]
        visible = staff.visible_task_events(events)
        self.assertEqual([e["text"] for e in visible], ["Задача создана", "Задача выполнена", "Возвращено на доработку. Причина: исправить", "Задача выполнена", "Инициатор подтвердил: выполнено полностью"])

    def test_initiator_deadline_stats(self):
        director=self.create("stats-d@example.com", "director")
        deputy=self.create("stats-a@example.com", "associate")
        teacher=self.create("stats-t@example.com", "teacher")
        dh,_=self.ready("stats-d@example.com", "director", director["password"])
        ah,_=self.ready("stats-a@example.com", "associate", deputy["password"])
        th,_=self.ready("stats-t@example.com", "teacher", teacher["password"])
        self.assertEqual(self.client.get("/api/staff/deadline-stats").status_code,401)
        self.assertEqual(self.client.get("/api/staff/deadline-stats",headers=th).status_code,403)
        empty=self.client.get("/api/staff/deadline-stats",headers=dh).json()
        self.assertEqual(empty,{"users":[]})
        project=self.client.post("/api/staff/projects",headers=ah,json={"title":"Проект заместителя"}).json()["id"]
        body={"assignee_id":teacher["user"]["id"],"description":"Задача","deadline":(staff.now()+timedelta(days=1)).isoformat()}
        ids=[self.client.post("/api/staff/tasks",headers=dh,json=body | ({"project_id":project} if i==0 else {})).json()["task"]["id"] for i in range(4)]
        self.client.post("/api/staff/tasks",headers=ah,json=body | {"project_id":project})
        current=datetime(2030,1,1,tzinfo=timezone.utc)
        before=(current-timedelta(days=1)).isoformat();after=(current+timedelta(days=1)).isoformat()
        with self.store.connect() as db:
            db.execute("UPDATE tasks SET deadline=? WHERE id=?",(after,ids[0]))
            db.execute("UPDATE tasks SET deadline=? WHERE id=?",(before,ids[1]))
            db.execute("UPDATE tasks SET deadline=?,completed_at=? WHERE id=?",(before,before,ids[2]))
            db.execute("UPDATE tasks SET deadline=?,completed_at=? WHERE id=?",(before,current.isoformat(),ids[3]))
        self.client.post(f"/api/staff/tasks/{ids[3]}/hide",headers=dh)
        with patch.object(staff,"now",return_value=current):
            result=self.client.get("/api/staff/deadline-stats",headers=dh).json()
            self.assertEqual(len(result["users"]),1)
            person=result["users"][0]
            self.assertEqual(person["id"],teacher["user"]["id"])
            self.assertEqual((person["completed_on_time"],person["overdue"]),(1,2))
            self.assertNotIn("email",person)
            self.assertEqual(len(self.client.get("/api/staff/deadline-stats",headers=ah).json()["users"]),1)
            with self.store.connect() as db:
                db.execute("UPDATE tasks SET completed_at=NULL,deadline=?,rework=1 WHERE id=?",(after,ids[3]))
            result=self.client.get("/api/staff/deadline-stats",headers=dh).json()
            self.assertEqual((result["users"][0]["completed_on_time"],result["users"][0]["overdue"]),(1,1))

    def test_deadline_stats_by_assignee_and_deleted_user(self):
        director=self.create("stat2-d@example.com", "director")
        other_director=self.create("stat2-a@example.com", "associate")
        first=self.create("stat2-t1@example.com", "teacher")
        second=self.create("stat2-t2@example.com", "teacher")
        dh,_=self.ready("stat2-d@example.com", "director", director["password"])
        ah,_=self.ready("stat2-a@example.com", "associate", other_director["password"])
        first_h,_=self.ready("stat2-t1@example.com", "teacher", first["password"])
        second_h,_=self.ready("stat2-t2@example.com", "teacher", second["password"])
        for headers in (first_h,second_h):
            self.client.put("/api/staff/profile",headers=headers,json={"full_name":"Иванов Иван", "position":"Учитель"})
        deadline=(staff.now()+timedelta(days=1)).isoformat()
        def create_for(headers, uid):
            return self.client.post("/api/staff/tasks",headers=headers,json={"assignee_id":uid,"description":"Задача","deadline":deadline}).json()["task"]
        first_task=create_for(dh,first["user"]["id"])
        second_task=create_for(dh,second["user"]["id"])
        create_for(ah,first["user"]["id"])
        self.client.put(f"/api/staff/tasks/{first_task['id']}/completion",headers=first_h,json={"completed":True})
        result=self.client.get("/api/staff/deadline-stats",headers=dh).json()["users"]
        self.assertEqual(len(result),2)
        by_id={p["id"]:p for p in result}
        self.assertEqual(by_id[first["user"]["id"]]["completed_on_time"],1)
        self.assertEqual(by_id[second["user"]["id"]]["completed_on_time"],0)
        self.assertTrue(all(p["full_name"]=="Иванов Иван" for p in result))
        self.client.delete("/api/admin/users/"+first["user"]["id"],headers=self.admin)
        result=self.client.get("/api/staff/deadline-stats",headers=dh).json()["users"]
        removed=next(p for p in result if p["id"]==first["user"]["id"])
        self.assertEqual(removed["full_name"],"Удалённый пользователь")
        self.assertEqual(removed["position"],"")
        self.assertEqual(removed["completed_on_time"],1)

    def test_duty_quarter_boundaries(self):
        cases=[(date(2026,9,1),date(2026,9,1),date(2026,10,31),1,True),
               (date(2026,10,31),date(2026,9,1),date(2026,10,31),1,True),
               (date(2026,11,1),date(2026,11,1),date(2026,12,31),2,True),
               (date(2027,1,9),date(2027,1,10),date(2027,3,31),3,False),
               (date(2027,1,10),date(2027,1,10),date(2027,3,31),3,True),
               (date(2027,3,31),date(2027,1,10),date(2027,3,31),3,True),
               (date(2027,4,1),date(2027,4,1),date(2027,5,31),4,True),
               (date(2027,6,1),date(2027,9,1),date(2027,10,31),1,False)]
        for today,start,end,quarter,active in cases:
            self.assertEqual(staff.duty_quarter(today),(start,end,quarter,active))

    def test_duty_booking_permissions_and_public_schedule(self):
        director=self.create("duty-d@example.com","director")
        deputy=self.create("duty-a@example.com","associate")
        teacher=self.create("duty-t@example.com","teacher")
        teacher2=self.create("duty-t2@example.com","teacher")
        dh,_=self.ready("duty-d@example.com","director",director["password"])
        ah,_=self.ready("duty-a@example.com","associate",deputy["password"])
        th,_=self.ready("duty-t@example.com","teacher",teacher["password"])
        th2,_=self.ready("duty-t2@example.com","teacher",teacher2["password"])
        for headers,name in [(ah,"Петрова Анна"),(th,"Иванов Иван"),(th2,"Сидорова Анна")]:
            self.client.put("/api/staff/profile",headers=headers,json={"full_name":name,"position":"Должность"})
        day="2026-11-09"
        with patch.object(staff,"school_today",return_value=date(2026,11,9)):
            self.assertEqual(self.client.get("/api/staff/duty").status_code,401)
            self.assertEqual(self.client.get("/api/staff/duty",headers=dh).status_code,403)
            calendar=self.client.get("/api/staff/duty",headers=th).json()
            self.assertEqual((calendar["quarter"],calendar["start"],calendar["end"]),(2,"2026-11-01","2026-12-31"))
            self.assertEqual(self.client.post("/api/staff/duty",headers=dh,json={"day":day,"shift":1,"class_name":"5А"}).status_code,403)
            self.assertEqual(self.client.post("/api/staff/duty",headers=th,json={"day":day,"shift":1,"class_name":" "}).status_code,422)
            self.assertEqual(self.client.post("/api/staff/duty",headers=th,json={"day":"2026-11-08","shift":1,"class_name":"5А"}).status_code,422)
            self.assertEqual(self.client.post("/api/staff/duty",headers=th,json={"day":"2027-01-10","shift":1,"class_name":"5А"}).status_code,422)
            self.assertEqual(self.client.post("/api/staff/duty",headers=ah,json={"day":day,"shift":1,"class_name":"5А"}).status_code,422)
            self.assertEqual(self.client.post("/api/staff/duty",headers=ah,json={"day":day}).status_code,201)
            self.assertEqual(self.client.post("/api/staff/duty",headers=th,json={"day":day,"shift":1,"class_name":" 5А "}).status_code,201)
            self.assertEqual(self.client.post("/api/staff/duty",headers=th2,json={"day":day,"shift":1,"class_name":"6А"}).status_code,409)
            self.assertEqual(self.client.post("/api/staff/duty",headers=th,json={"day":day,"shift":2,"class_name":"5А"}).status_code,409)
            self.assertEqual(self.client.post("/api/staff/duty",headers=th2,json={"day":day,"shift":2,"class_name":"6А"}).status_code,201)
            public=self.client.get("/api/duties/today").json()
            self.assertEqual([e["slot"] for e in public["entries"]],[0,1,2])
            self.assertEqual(public["entries"][1]["full_name"],"Иванов Иван")
            self.assertEqual(public["entries"][1]["class_name"],"5А")
            self.assertNotIn("email",str(public));self.assertNotIn("user_id",str(public))
            self.assertEqual(self.client.delete(f"/api/staff/duty/{day}/1",headers=th2).status_code,404)
            self.assertEqual(self.client.delete(f"/api/staff/duty/{day}/1",headers=th).status_code,200)
            self.assertEqual(self.client.post("/api/staff/duty",headers=th2,json={"day":day,"shift":1,"class_name":"6А"}).status_code,409)
            # Password resets do not delete duty records; user deletion releases future slots.
            self.client.post(f"/api/admin/users/{teacher2['user']['id']}/password/reset",headers=self.admin)
            self.assertEqual(len(self.client.get("/api/duties/today").json()["entries"]),2)
            self.client.delete(f"/api/admin/users/{teacher2['user']['id']}",headers=self.admin)
            self.assertEqual(len(self.client.get("/api/duties/today").json()["entries"]),1)
        with patch.object(staff,"school_today",return_value=date(2027,6,1)):
            self.assertFalse(self.client.get("/api/staff/duty",headers=ah).json()["active"])
            self.assertEqual(self.client.post("/api/staff/duty",headers=ah,json={"day":"2027-09-01"}).status_code,422)

    def test_repeating_deputy_week_and_single_date_override(self):
        a=self.create("week-a@example.com","associate")
        b=self.create("week-b@example.com","associate")
        t=self.create("week-teacher@example.com","teacher")
        d=self.create("week-director@example.com","director")
        ah,_=self.ready("week-a@example.com","associate",a["password"])
        bh,_=self.ready("week-b@example.com","associate",b["password"])
        th,_=self.ready("week-teacher@example.com","teacher",t["password"])
        dh,_=self.ready("week-director@example.com","director",d["password"])
        for headers,name in ((ah,"Анна"),(bh,"Борис"),(th,"Учитель")):
            self.client.put("/api/staff/profile",headers=headers,json={"full_name":name})
        aid,bid=a["user"]["id"],b["user"]["id"]
        week={"deputies":[aid,bid,aid,bid,aid]}
        url="/api/staff/duty/week-template"
        with patch.object(staff,"school_today",return_value=date(2026,11,9)):
            self.assertEqual(self.client.get(url,headers=th).status_code,403)
            self.assertEqual(self.client.put(url,headers=dh,json=week).status_code,403)
            self.assertEqual(self.client.put(url,headers=ah,json={"deputies":[aid]}).status_code,422)
            self.assertEqual(self.client.put(url,headers=ah,json={"deputies":[aid,bid,aid,bid,t["user"]["id"]]}).status_code,404)
            self.assertEqual(self.client.post("/api/staff/duty",headers=bh,json={"day":"2026-11-16"}).status_code,201)
            self.assertEqual(self.client.put(url,headers=ah,json=week).status_code,200)
            self.assertEqual(self.client.get(url,headers=ah).json()["week"],week["deputies"])
            entries=self.client.get("/api/staff/duty",headers=ah).json()["entries"]
            admin={e["day"]:e for e in entries if e["slot"]==0}
            self.assertEqual((admin["2026-11-09"]["full_name"],admin["2026-11-09"]["source"]),("Анна","template"))
            self.assertEqual(admin["2026-11-10"]["full_name"],"Борис")
            self.assertEqual((admin["2026-11-16"]["full_name"],admin["2026-11-16"]["source"]),("Борис","manual"))
            self.assertNotIn("2026-11-14",admin)
            self.assertEqual(self.client.get("/api/duties/today").json()["entries"][0]["full_name"],"Анна")
            self.assertEqual(self.client.post("/api/staff/duty",headers=bh,json={"day":"2026-11-09"}).status_code,409)
            override="/api/staff/duty/admin/2026-11-09"
            self.assertEqual(self.client.put(override,headers=th,json={"user_id":bid}).status_code,403)
            self.assertEqual(self.client.put(override,headers=ah,json={"user_id":t["user"]["id"]}).status_code,404)
            self.assertEqual(self.client.put(override,headers=ah,json={"user_id":bid}).status_code,200)
            self.assertEqual(self.client.get("/api/duties/today").json()["entries"][0]["full_name"],"Борис")
            self.assertEqual(self.client.put(override,headers=ah,json={"user_id":None}).status_code,200)
            self.assertEqual(self.client.get("/api/duties/today").json()["entries"],[])
            self.assertEqual(self.client.delete(override,headers=ah).status_code,200)
            self.assertEqual(self.client.get("/api/duties/today").json()["entries"][0]["full_name"],"Анна")
            self.assertEqual(self.client.delete("/api/staff/duty/2026-11-09/0",headers=ah).status_code,200)
            self.assertEqual(self.client.get("/api/duties/today").json()["entries"],[])
            self.assertEqual(self.client.post("/api/staff/duty",headers=bh,json={"day":"2026-11-09"}).status_code,201)
            self.assertEqual(self.client.get("/api/duties/today").json()["entries"][0]["full_name"],"Борис")
            self.assertEqual(self.client.put("/api/staff/duty/admin/2026-11-16",headers=ah,json={"user_id":aid}).status_code,200)
            self.assertEqual(self.client.delete("/api/staff/duty/admin/2026-11-16",headers=ah).status_code,200)
            self.assertEqual(next(e for e in self.client.get("/api/staff/duty",headers=ah).json()["entries"] if e["day"]=="2026-11-16")["full_name"],"Борис")
        with patch.object(staff,"school_today",return_value=date(2026,11,17)):
            self.assertEqual(self.client.put(url,headers=ah,json={"deputies":[bid]*5}).status_code,200)
            self.assertEqual(self.client.put("/api/staff/duty/admin/2026-11-16",headers=ah,json={"user_id":aid}).status_code,422)
            entries=self.client.get("/api/staff/duty",headers=ah).json()["entries"]
            self.assertEqual(next(e for e in entries if e["day"]=="2026-11-11")["full_name"],"Анна")
            self.assertEqual(next(e for e in entries if e["day"]=="2026-11-18")["full_name"],"Борис")
        with patch.object(staff,"school_today",return_value=date(2027,1,4)):
            self.assertEqual(self.client.get("/api/duties/today").json()["entries"],[])
        with patch.object(staff,"school_today",return_value=date(2027,1,11)):
            self.assertEqual(self.client.get("/api/duties/today").json()["entries"][0]["full_name"],"Борис")
            self.client.delete(f"/api/admin/users/{bid}",headers=self.admin)
            self.assertEqual(self.client.get("/api/duties/today").json()["entries"],[])

    def test_deputy_assigns_registered_teachers_to_duty(self):
        deputy=self.create("assign-a@example.com","associate")
        teacher=self.create("assign-t@example.com","teacher")
        teacher2=self.create("assign-t2@example.com","teacher")
        no_name=self.create("assign-blank@example.com","teacher")
        director=self.create("assign-d@example.com","director")
        ah,_=self.ready("assign-a@example.com","associate",deputy["password"])
        th,_=self.ready("assign-t@example.com","teacher",teacher["password"])
        dh,_=self.ready("assign-d@example.com","director",director["password"])
        for headers,name in [(th,"Учитель Иван"),(ah,"Завуч")]:
            self.client.put("/api/staff/profile",headers=headers,json={"full_name":name})
        tid=teacher["user"]["id"]
        data={"day":"2026-11-09","shift":1,"class_name":" 5А ","teacher_id":tid}
        with patch.object(staff,"school_today",return_value=date(2026,11,9)):
            post=lambda headers, body:self.client.post("/api/staff/duty",headers=headers,json=body)
            self.assertEqual(post(dh,data).status_code,403)
            self.assertEqual(post(th,data).status_code,403)
            self.assertEqual(post(ah,{**data,"teacher_id":deputy["user"]["id"]}).status_code,404)
            self.assertEqual(post(ah,{**data,"teacher_id":director["user"]["id"]}).status_code,404)
            self.assertEqual(post(ah,{**data,"teacher_id":"unknown"}).status_code,404)
            self.assertEqual(post(ah,{**data,"teacher_id":no_name["user"]["id"]}).status_code,422)
            self.assertEqual(post(ah,{**data,"class_name":" "}).status_code,422)
            self.assertEqual(post(ah,{**data,"shift":None}).status_code,422)
            self.assertEqual(post(ah,{**data,"day":"2026-11-08"}).status_code,422)
            self.assertEqual(post(ah,data).status_code,201)
            self.assertEqual(post(ah,{**data,"shift":2}).status_code,409)
            entry=self.client.get("/api/staff/duty",headers=th).json()["entries"][0]
            self.assertTrue(entry["mine"])
            self.assertEqual((entry["full_name"],entry["class_name"]),("Учитель Иван","5А"))
            self.assertEqual(self.client.get("/api/duties/today").json()["entries"][0]["full_name"],"Учитель Иван")
            self.assertEqual(self.client.delete("/api/staff/duty/2026-11-09/1",headers=ah).status_code,404)
            self.assertEqual(self.client.delete("/api/staff/duty/2026-11-09/1",headers=th).status_code,200)
            self.client.delete(f"/api/admin/users/{teacher2['user']['id']}",headers=self.admin)
            self.assertEqual(post(ah,{**data,"teacher_id":teacher2["user"]["id"]}).status_code,404)

    def test_deputy_assignment_races_teacher_reservation(self):
        deputy=self.create("race-deputy@example.com","associate")
        t1=self.create("race-assign1@example.com","teacher")
        t2=self.create("race-assign2@example.com","teacher")
        ah,_=self.ready("race-deputy@example.com","associate",deputy["password"])
        h1,_=self.ready("race-assign1@example.com","teacher",t1["password"])
        h2,_=self.ready("race-assign2@example.com","teacher",t2["password"])
        for headers in (h1,h2):self.client.put("/api/staff/profile",headers=headers,json={"full_name":"Учитель"})
        day="2026-09-02"
        with patch.object(staff,"school_today",return_value=date(2026,9,1)):
            def reserve(request):
                headers,body=request
                return self.client.post("/api/staff/duty",headers=headers,json=body).status_code
            with ThreadPoolExecutor(max_workers=2) as executor:
                results=list(executor.map(reserve,[(ah,{"day":day,"shift":1,"class_name":"5А","teacher_id":t1["user"]["id"]}),(h2,{"day":day,"shift":1,"class_name":"6А"})]))
            self.assertEqual(sorted(results),[201,409])
            self.assertEqual(len(self.client.get("/api/staff/duty",headers=h1).json()["entries"]),1)

    def test_duty_competing_reservations_are_atomic(self):
        t1=self.create("race1@example.com","teacher")
        t2=self.create("race2@example.com","teacher")
        h1,_=self.ready("race1@example.com","teacher",t1["password"])
        h2,_=self.ready("race2@example.com","teacher",t2["password"])
        for headers in (h1,h2):self.client.put("/api/staff/profile",headers=headers,json={"full_name":"Учитель"})
        with patch.object(staff,"school_today",return_value=date(2026,9,1)):
            def reserve(headers):
                return self.client.post("/api/staff/duty",headers=headers,json={"day":"2026-09-02","shift":1,"class_name":"5А"}).status_code
            with ThreadPoolExecutor(max_workers=2) as executor:
                results=list(executor.map(reserve,(h1,h2)))
            self.assertEqual(sorted(results),[201,409])
            self.assertEqual(len(self.client.get("/api/staff/duty",headers=h1).json()["entries"]),1)

    def test_bruteforce_throttle(self):
        user = self.create("a@example.com", "associate")
        for _ in range(5):
            self.assertEqual(self.login("a@example.com", "associate", "wrong").status_code, 401)
        self.assertEqual(self.login("a@example.com", "associate", user["password"]).status_code, 429)
        new = self.client.post(f"/api/admin/users/{user['user']['id']}/password/reset", headers=self.admin).json()["password"]
        self.assertEqual(self.login("a@example.com", "associate", new).status_code, 200)


if __name__ == "__main__":
    unittest.main()
