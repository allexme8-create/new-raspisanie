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
    def test_bell_manual_editor_validation_and_revision(self):
        from schedule_parser import parse_bell_schedule_file
        old=copy.deepcopy(backend.state)
        try:
            backend.state["bell_schedule"]={"filename":"test.xlsx",**bells()}
            with patch.object(backend,"_save_state") as save, TestClient(backend.app) as client:
                url="/api/admin/bell-schedule/editor"
                headers={"Authorization":"Bearer "+backend._create_token()}
                self.assertEqual(client.get(url).status_code,401)
                loaded=client.get(url,headers=headers).json()
                self.assertEqual(loaded["shifts"]["1"]["Пн"]["1"]["start"],"08:00")
                entry={"day":"Пн","shift":1,"lesson":1,"start":"08:00","end":"08:40"}
                payload={"revision":loaded["revision"],"entries":[entry]}
                self.assertEqual(client.put(url,json=payload).status_code,401)
                self.assertEqual(client.put(url,headers=headers,json={**payload,"entries":[{**entry,"end":"07:00"}]}).status_code,422)
                self.assertEqual(client.put(url,headers=headers,json={**payload,"entries":[entry,entry]}).status_code,422)
                self.assertEqual(client.put(url,headers=headers,json={**payload,"entries":[entry,{**entry,"lesson":2,"start":"08:30","end":"09:00"}]}).status_code,422)
                self.assertEqual(client.put(url,headers=headers,json={**payload,"entries":[]}).status_code,422)
                self.assertEqual(save.call_count,0)
                result=client.put(url,headers=headers,json=payload)
                self.assertEqual(result.status_code,200,result.text)
                self.assertEqual(save.call_count,1)
                self.assertEqual(client.get("/api/schedule").json()["bell_schedule"]["shifts"]["1"]["Пн"]["1"],{"start":"08:00","end":"08:40"})
                self.assertEqual(parse_bell_schedule_file(client.get("/api/schedule/bell-schedule.csv").content,"bells.csv")["shifts"],{"1":{"Пн":{"1":{"start":"08:00","end":"08:40"}}},"2":{}})
                self.assertEqual(client.put(url,headers=headers,json=payload).status_code,409)
                self.assertEqual(save.call_count,1)
        finally:
            backend.state.clear();backend.state.update(old)

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

    def test_import_subjects_and_rooms_preserves_existing_and_does_not_resurrect(self):
        old=copy.deepcopy(backend.state)
        try:
            backend.state["planner"]=project().model_dump()
            backend.state["planner_subjects_imported"]=False;backend.state["planner_rooms_imported"]=False
            backend.state["subjects"]={"grid":{"Пн":{"1":{"5а":{"names":["Математика","Физика","физика","Классный час"],"rooms":["101", " 103 "]}}}}}
            backend.state["teachers"]={"grid":{"Пн":{"1":{"5а":{"names":["Учитель"],"rooms":["103", "спортзал"]}}}}}
            with patch.object(backend,"_save_state"):
                backend.migrate_schedule_catalogs()
                p=backend._planner_project()
                self.assertEqual([x.name for x in p.subjects],["Математика","Физика"])
                self.assertEqual([x.name for x in p.rooms],["101","102","103","спортзал"])
                self.assertEqual(len(p.loads),2)
                backend.state["planner"]["subjects"]=[x for x in backend.state["planner"]["subjects"] if x["name"]!="Физика"]
                backend.migrate_schedule_catalogs()
                self.assertNotIn("Физика",[x.name for x in backend._planner_project().subjects])
                self.assertEqual(backend.import_schedule_catalog("subjects")["added"],["Физика"])
                self.assertEqual(backend.import_schedule_catalog("rooms")["added"],[])
                with self.assertRaises(backend.HTTPException):backend.import_schedule_catalog("teachers")
        finally:
            backend.state.clear();backend.state.update(old)

    def test_rename_subjects_rooms_preserves_load_and_placements(self):
        old=copy.deepcopy(backend.state)
        with tempfile.TemporaryDirectory() as folder:
            store=staff.Store(Path(folder)/"staff.sqlite3");store.init()
            try:
                p=project();p.placements=[planner.Placement(load_id="a",day="Пн",lesson=1)];backend.state["planner"]=p.model_dump()
                with patch.object(backend,"staff_store",store),patch.object(backend,"_save_state"):
                    result=backend.planner_rename("subjects",backend.PlannerRename(revision=0,old_name="Математика",new_name="Алгебра"))
                    self.assertEqual(result["project"]["loads"][0]["subject"],"Алгебра")
                    result=backend.planner_rename("rooms",backend.PlannerRename(revision=1,old_name="101",new_name="103"))
                    self.assertEqual(result["project"]["loads"][0]["room"],"103")
                    self.assertEqual(result["project"]["placements"][0]["load_id"],"a")
                    with self.assertRaises(backend.HTTPException):backend.planner_rename("rooms",backend.PlannerRename(revision=2,old_name="103",new_name="102"))
                    with self.assertRaises(backend.HTTPException):backend.planner_rename("rooms",backend.PlannerRename(revision=1,old_name="103",new_name="104"))
            finally:
                backend.state.clear();backend.state.update(old)

    def test_planner_rename_updates_loads_and_class_leadership(self):
        old=copy.deepcopy(backend.state)
        with tempfile.TemporaryDirectory() as folder:
            store=staff.Store(Path(folder)/"staff.sqlite3");store.init()
            with store.connect() as db:
                db.execute("INSERT INTO users (id,email,role,password_hash,must_change,active,created_at,homeroom_class) VALUES (?,?,?, ?,0,1,?,?)",("t","t@example.com","teacher","hash","2026-01-01","5а"))
                db.execute("INSERT INTO duty_assignments(day,slot,user_id,class_name) VALUES (?,?,?,?)",("2026-01-01",1,"t","5а"))
            try:
                backend.state["planner"]=project().model_dump()
                with patch.object(backend,"staff_store",store),patch.object(backend,"_save_state"):
                    with self.assertRaises(backend.HTTPException):
                        backend.planner_rename("classes",backend.PlannerRename(revision=2,old_name="5а",new_name="5б"))
                    result=backend.planner_rename("classes",backend.PlannerRename(revision=0,old_name="5а",new_name="5б"))
                    self.assertEqual(result["project"]["loads"][0]["class_name"],"5б")
                    with store.connect() as db:
                        self.assertEqual(db.execute("SELECT homeroom_class FROM users").fetchone()[0],"5б")
                        self.assertEqual(db.execute("SELECT class_name FROM duty_assignments").fetchone()[0],"5а")
                    result=backend.planner_rename("teachers",backend.PlannerRename(revision=1,old_name="Учитель",new_name="Иванов ИИ"))
                    self.assertEqual(result["project"]["teachers"][0]["name"],"Иванов И.И.")
                    self.assertEqual(result["project"]["loads"][0]["teacher"],"Иванов И.И.")
                    self.assertEqual(backend.normalize_teacher_initials("Петров А. Б."),"Петров А.Б.")
                    self.assertEqual(backend.normalize_teacher_initials("Петров Антон Борисович"),"Петров Антон Борисович")
            finally:
                backend.state.clear();backend.state.update(old)

    def test_import_schedule_teachers_once_without_duplicates_or_service_rows(self):
        old=copy.deepcopy(backend.state)
        try:
            backend.state["planner"]=project().model_dump()
            backend.state["planner_teachers_imported"]=False
            backend.state["teachers"]={"classes":["5а"],"grid":{"Пн":{"1":{"5а":{"names":["Учитель", "Иванов ИИ", "Классный час", "Иванов ИИ", "ошибка"]}},"2":{"5а":{"names":["Петрова АА"]}}}}}
            with patch.object(backend,"_save_state") as save:
                backend.migrate_schedule_teachers()
                names=[x.name for x in backend._planner_project().teachers]
                self.assertEqual(names,["Учитель","Другой","Иванов И.И.","Петрова А.А."])
                self.assertTrue(backend.state["planner_teachers_imported"])
                self.assertEqual(len(backend._planner_project().loads),2)
                self.assertEqual(save.call_count,1)
                backend.state["planner"]["teachers"]=[x for x in backend.state["planner"]["teachers"] if x["name"]!="Иванов И.И."]
                backend.migrate_schedule_teachers()
                self.assertNotIn("Иванов И.И.",[x.name for x in backend._planner_project().teachers])
                self.assertEqual(backend.import_schedule_teachers()["added"],["Иванов И.И."])
                self.assertEqual(backend.import_schedule_teachers()["added"],[])
        finally:
            backend.state.clear();backend.state.update(old)

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

    def test_group_catalog_import_rename_and_deletion_safety(self):
        old=copy.deepcopy(backend.state)
        with tempfile.TemporaryDirectory() as folder:
            store=staff.Store(Path(folder)/"staff.sqlite3");store.init()
            try:
                p=project();p.loads[0].group="Красная";backend.state["planner"]=p.model_dump();backend.state["planner_groups_imported"]=False
                backend.state["teachers"]={"grid":{"Пн":{"1":{"5а":{"names":["Учитель","Другой"]}},"2":{"6а":{"names":["Учитель"],"groups":[{"group":"Языковая"}]}}}}}
                backend.state["subjects"]=None
                with patch.object(backend,"staff_store",store),patch.object(backend,"_save_state"):
                    backend.migrate_schedule_groups();current=backend._planner_project()
                    groups={(g.class_name,g.name):g.inferred for g in current.groups}
                    self.assertFalse(groups[("5а","Красная")]);self.assertTrue(groups[("5а","1 группа")]);self.assertTrue(groups[("5а","2 группа")]);self.assertFalse(groups[("6а","Языковая")])
                    self.assertEqual(backend.import_schedule_groups()["added"],[])
                    revision=current.revision
                    response=backend.planner_rename_group(backend.PlannerGroupRename(revision=revision,class_name="5а",old_name="Красная",new_name="Синяя"))
                    self.assertEqual(response["project"]["loads"][0]["group"],"Синяя")
                    with self.assertRaises(backend.HTTPException):backend.planner_rename_group(backend.PlannerGroupRename(revision=revision,class_name="5а",old_name="Синяя",new_name="Другие"))
                    edited=backend._planner_project();edited.groups=[g for g in edited.groups if g.name!="Синяя"]
                    with self.assertRaises(backend.HTTPException) as exc:backend.planner_save(edited)
                    self.assertEqual(exc.exception.status_code,409)
                    current=backend._planner_project();current.groups=[g for g in current.groups if g.name!="1 группа"]
                    backend.planner_save(current);backend.migrate_schedule_groups()
                    self.assertNotIn("1 группа",[g.name for g in backend._planner_project().groups])
                    self.assertTrue(backend.import_schedule_groups()["added"])
            finally:
                backend.state.clear();backend.state.update(old)

    def test_parallel_groups_conflicts_limits_generation_and_publication(self):
        p=project();p.classes=p.classes[:1];p.classes[0].max_daily=1
        p.loads=[planner.Load(id="g1",class_name="5а",subject="Математика",teacher="Учитель",room="101",per_week=1,group="1 группа"),planner.Load(id="g2",class_name="5а",subject="Математика",teacher="Другой",room="102",per_week=1,group="2 группа")]
        p.placements=[planner.Placement(load_id="g1",day="Пн",lesson=1),planner.Placement(load_id="g2",day="Пн",lesson=1)]
        self.assertEqual(planner.issues(p,bells(),complete=True),[])
        teacher_grid,subject_grid=planner.public_grids(p)
        cell=subject_grid["grid"]["Пн"]["1"]["5а"]
        self.assertEqual([g["group"] for g in cell["groups"]],["1 группа","2 группа"])
        self.assertEqual(cell["names"],["Математика","Математика"])
        self.assertEqual(teacher_grid["grid"]["Пн"]["1"]["5а"]["rooms"],["101","102"])
        p.loads[1].group="1 ГРУППА";self.assertTrue(any("группа" in e for e in planner.issues(p,bells())))
        p.loads[1].group="";self.assertTrue(any("группа" in e for e in planner.issues(p,bells())))
        p.loads[1].group="2 группа";p.loads[1].teacher="Учитель";self.assertTrue(any("учитель" in e for e in planner.issues(p,bells())))
        p.loads[1].teacher="Другой";p.loads[1].room="101";self.assertTrue(any("кабинет" in e for e in planner.issues(p,bells())))
        p.loads[1].room="102";p.placements=[]
        b={"shifts":{"1":{"Пн":{"1":{"start":"08:00","end":"08:40"}}},"2":{}}}
        generated,error=planner.generate(p,b)
        self.assertIsNotNone(generated,error);self.assertEqual([(x.day,x.lesson) for x in generated.placements],[("Пн",1),("Пн",1)])
        self.assertEqual(planner.issues(generated,b,complete=True),[])

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
