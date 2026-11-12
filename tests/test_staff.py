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

    def test_bruteforce_throttle(self):
        user = self.create("a@example.com", "associate")
        for _ in range(5):
            self.assertEqual(self.login("a@example.com", "associate", "wrong").status_code, 401)
        self.assertEqual(self.login("a@example.com", "associate", user["password"]).status_code, 429)
        new = self.client.post(f"/api/admin/users/{user['user']['id']}/password/reset", headers=self.admin).json()["password"]
        self.assertEqual(self.login("a@example.com", "associate", new).status_code, 200)


if __name__ == "__main__":
    unittest.main()
