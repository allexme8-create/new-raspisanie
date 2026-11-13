from __future__ import annotations

import copy
import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import app as backend
import planner
import staff
from fastapi.testclient import TestClient


def bells():
    return {"shifts": {
        "1": {d: {"1": {"start": "08:00", "end": "08:40"}, "2": {"start": "09:00", "end": "09:40"}} for d in planner.DAYS},
        "2": {d: {"1": {"start": "08:20", "end": "09:00"}, "2": {"start": "10:00", "end": "10:40"}} for d in planner.DAYS},
    }}


def project():
    return planner.Project.model_validate({
        "classes": [{"name": "5а"}, {"name": "6а", "shift": 2}],
        "teachers": [{"name": "Учитель"}, {"name": "Другой"}],
        "subjects": [{"name": "Математика"}],
        "rooms": [{"name": "101"}, {"name": "102"}],
        "loads": [
            {"id": "a", "class_name": "5а", "teacher": "Учитель", "subject": "Математика", "room": "101", "per_week": 2},
            {"id": "b", "class_name": "6а", "teacher": "Учитель", "subject": "Математика", "room": "102", "per_week": 1},
        ],
    })


class PlannerTests(unittest.TestCase):
    def test_bell_csv_download_auth_and_roundtrip(self):
        from schedule_parser import parse_bell_schedule_file
        old=backend.state.get("bell_schedule")
        sample={"1":{"Пн":{"2":{"start":"09:15","end":"09:55"},"1":{"start":"08:25","end":"09:05"}},"Сб":{"1":{"start":"08:00","end":"08:40"}}},"2":{"Вт":{"1":{"start":"13:30","end":"14:10"}}}}
        try:
            backend.state["bell_schedule"]={"filename":"original.xlsx","shifts":sample}
            with TestClient(backend.app) as client:
                url="/api/admin/bell-schedule.csv"
                self.assertEqual(client.get(url).status_code,401)
                headers={"Authorization":"Bearer "+backend._create_token()}
                response=client.get(url,headers=headers)
                self.assertEqual(response.status_code,200)
                public_response=client.get("/api/schedule/bell-schedule.csv")
                self.assertEqual(public_response.status_code,200)
                self.assertEqual(response.content,public_response.content)
                self.assertIn("attachment",response.headers["content-disposition"])
                self.assertIn("no-store",response.headers["cache-control"])
                self.assertEqual(parse_bell_schedule_file(response.content,"bells.csv")["shifts"],sample)
                backend.state["bell_schedule"]=None
                self.assertEqual(client.get(url,headers=headers).status_code,404)
        finally:
            backend.state["bell_schedule"]=old

    def test_unified_staff_page_and_admin_routes(self):
        with TestClient(backend.app) as client:
            response = client.get("/users")
            self.assertEqual(response.status_code, 200)
            self.assertIn("no-store", response.headers["cache-control"])
            self.assertIn('id="staffLoginCard"', response.text)
            self.assertEqual(client.get("/admin").status_code, 200)
            for old_path in ("/teacher", "/Director", "/associate"):
                self.assertEqual(client.get(old_path).status_code, 404)

    def test_migrate_schedule_classes_and_preserve_planner(self):
        original=copy.deepcopy(backend.state)
        try:
            backend.state["planner"]=project().model_dump()
            backend.state["teachers"]={"classes":["5а","7б","8в"],"grid":{}}
            backend.state["subjects"]={"classes":["7б","9г"],"grid":{}}
            backend.state["second_shift_classes"]=["7б"]
            backend.state["planner_class_imported"]=False
            with patch.object(backend,"_save_state") as save:
                backend.migrate_schedule_classes()
                result=backend._planner_project()
                self.assertEqual([c.name for c in result.classes],["5а","6а","7б","8в","9г"])
                self.assertEqual(next(c.shift for c in result.classes if c.name=="7б"),2)
                self.assertEqual(result.revision,1)
                self.assertEqual(len(result.loads),2)
                self.assertTrue(backend.state["planner_class_imported"])
                save.assert_called_once()
                self.assertEqual(backend.import_schedule_classes()["added"],[])
                backend.state["planner"]["classes"]=[c for c in backend.state["planner"]["classes"] if c["name"]!="7б"]
                backend.migrate_schedule_classes()
                self.assertNotIn("7б",[c.name for c in backend._planner_project().classes])
                self.assertEqual(backend.import_schedule_classes()["added"],["7б"])
        finally:
            backend.state.clear();backend.state.update(original)

    def test_uploaded_schedule_adds_classes_without_overwriting_draft(self):
        original=copy.deepcopy(backend.state)
        try:
            backend.state["planner"]=project().model_dump()
            backend.state["teachers"]=None;backend.state["subjects"]=None
            with tempfile.TemporaryDirectory() as folder,patch.object(backend,"UPLOAD_DIR",Path(folder)),patch.object(backend,"_save_state"),patch.object(backend,"parse_schedule_file",return_value=("teachers",{"classes":["10а","5а"],"grid":{}})):
                backend._ingest(b"file","schedule.xlsx")
                result=backend._planner_project()
                self.assertIn("10а",[c.name for c in result.classes])
                self.assertEqual(result.revision,1)
                self.assertEqual(len(result.loads),2)
        finally:
            backend.state.clear();backend.state.update(original)

    def test_cannot_remove_class_with_homeroom_teacher(self):
        original=copy.deepcopy(backend.state)
        with tempfile.TemporaryDirectory() as folder:
            store=staff.Store(Path(folder)/"staff.sqlite3");store.init()
            with store.connect() as db:
                db.execute("INSERT INTO users (id,email,role,password_hash,must_change,active,created_at,homeroom_class) VALUES (?,?,?, ?,0,1,?,?)",("t","t@example.com","teacher","hash","2026-01-01","5а"))
            try:
                backend.state["planner"]=project().model_dump()
                with patch.object(backend,"_save_state"),patch.object(backend,"staff_store",store):
                    changed=project();changed.classes=[c for c in changed.classes if c.name!="5а"];changed.loads=[l for l in changed.loads if l.class_name!="5а"]
                    with self.assertRaises(backend.HTTPException) as exc:backend.planner_save(changed)
                    self.assertEqual(exc.exception.status_code,409)
                    self.assertIn("классным руководителем",str(exc.exception.detail))
                    with store.connect() as db:db.execute("UPDATE users SET homeroom_class='' WHERE id='t'")
                    self.assertEqual([c["name"] for c in backend.planner_save(changed)["project"]["classes"]],["6а"])
            finally:
                backend.state.clear();backend.state.update(original)

    def test_conflicts_use_real_times_across_shifts(self):
        p = project()
        p.placements = [planner.Placement(load_id="a", day="Пн", lesson=1), planner.Placement(load_id="b", day="Пн", lesson=1)]
        self.assertTrue(any("учитель" in issue for issue in planner.issues(p, bells())))
        p.placements[1].lesson = 2
        self.assertFalse(planner.issues(p, bells()))
        p.loads[1].room = "101"
        p.placements[1].lesson = 1
        self.assertTrue(any("кабинет" in issue for issue in planner.issues(p, bells())))

    def test_unavailable_applies_to_overlapping_shift(self):
        p = project()
        p.teachers[0].unavailable = [planner.Slot(day="Пн", shift=1, lesson=1)]
        p.placements = [planner.Placement(load_id="b", day="Пн", lesson=1)]
        self.assertTrue(any("недоступен" in issue for issue in planner.issues(p, bells())))
        self.assertTrue(any("нет звонков" in issue for issue in planner.issues(p, None)))

    def test_generate_preserves_manual_placements_and_validates(self):
        p = project()
        p.placements = [planner.Placement(load_id="a", day="Пн", lesson=1)]
        generated, error = planner.generate(p, bells())
        self.assertEqual(error, "")
        self.assertIsNotNone(generated)
        self.assertEqual(generated.placements[0], p.placements[0])
        self.assertEqual(len(p.placements), 1)
        self.assertEqual(planner.issues(generated, bells(), complete=True), [])
        teachers, subjects = planner.public_grids(generated)
        self.assertEqual(teachers["numbering"], "local")
        self.assertEqual(subjects["numbering"], "local")
        self.assertEqual(teachers["grid"]["Пн"]["1"]["5а"]["rooms"], ["101"])

    def test_daily_limits_and_missing_bells(self):
        p = project()
        p.classes[0].max_daily = 1
        p.placements = [planner.Placement(load_id="a", day="Пн", lesson=1), planner.Placement(load_id="a", day="Пн", lesson=2)]
        errors = planner.issues(p, bells())
        self.assertTrue(any("дневной предел уроков" in x for x in errors))
        self.assertTrue(any("дневной предел нагрузки" in x for x in errors))
        self.assertTrue(any("нет времени звонков" in x for x in planner.issues(p, None)))

    def test_failure_does_not_change_draft(self):
        p = project()
        before = p.model_dump()
        generated, error = planner.generate(p, None)
        self.assertIsNone(generated)
        self.assertTrue(error)
        self.assertEqual(before, p.model_dump())

    def test_reference_validation_and_incomplete(self):
        p = project()
        self.assertTrue(any("расставлено" in x for x in planner.issues(p, bells(), complete=True)))
        p.rooms = []
        self.assertTrue(any("кабинет" in x for x in planner.references(p)))

    def test_api_publish_and_revision_guard(self):
        original = copy.deepcopy(backend.state)
        try:
            backend.state["planner"] = None
            backend.state["bell_schedule"] = bells()
            with tempfile.TemporaryDirectory() as folder, patch.object(backend, "_save_state"):
                store=staff.Store(Path(folder)/"staff.sqlite3");store.init()
                with patch.object(backend,"staff_store",store):
                    p = project()
                    saved = backend.planner_save(p)
                with self.assertRaises(backend.HTTPException) as conflict:
                    backend.planner_save(project())
                self.assertEqual(conflict.exception.status_code, 409)
                with self.assertRaises(backend.HTTPException):
                    backend.planner_publish(backend.PlannerAction(revision=saved["project"]["revision"]))
                generated = backend.planner_generate(backend.PlannerAction(revision=saved["project"]["revision"]))
                backend.planner_publish(backend.PlannerAction(revision=generated["project"]["revision"]))
                self.assertEqual(backend.state["second_shift_classes"], ["6а"])
                self.assertEqual(backend.state["subjects"]["numbering"], "local")
        finally:
            backend.state.clear()
            backend.state.update(original)


if __name__ == "__main__":
    unittest.main()
