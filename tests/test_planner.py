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
    def test_teacher_windows_take_priority_over_soft_preferences(self):
        p=planner.Project(classes=[planner.SchoolClass(name='5а'),planner.SchoolClass(name='6а')],teachers=[planner.Teacher(name='А')],subjects=[planner.Named(name='Математика')],rooms=[planner.Room(name='101')],loads=[planner.Load(id='fixed',class_name='5а',teacher='А',subject='Математика',room='101',per_week=1),planner.Load(id='new',class_name='6а',teacher='А',subject='Математика',room='101',per_week=1)],placements=[planner.Placement(load_id='fixed',day='Пн',lesson=1)],preferences=[planner.Preference(scope='class',scope_value='6а',subject='Математика',kind='avoid_lesson',lesson=2)])
        schedule={'shifts':{'1':{'Пн':{'1':{'start':'08:00','end':'08:40'},'2':{'start':'09:00','end':'09:40'},'3':{'start':'10:00','end':'10:40'}}}}}
        result,error=planner.generate(p,schedule);self.assertIsNotNone(result,error)
        self.assertEqual(next(x.lesson for x in result.placements if x.load_id=='new'),2)
        self.assertEqual(planner.teacher_gap_summary(result,schedule)['total'],0)
        self.assertEqual(len(planner.preference_warnings(result)),1)
        self.assertEqual(p.placements[0].lesson,1);self.assertEqual(len(p.placements),1)

    def test_teacher_windows_unavoidable_fixed_and_cross_shift(self):
        schedule={'shifts':{'1':{'Пн':{'1':{'start':'08:00','end':'08:40'},'2':{'start':'09:00','end':'09:40'},'3':{'start':'10:00','end':'10:40'}}},'2':{'Пн':{'1':{'start':'09:10','end':'09:30'},'2':{'start':'10:00','end':'10:40'}}}}}
        p=planner.Project(classes=[planner.SchoolClass(name='5а',shift=1),planner.SchoolClass(name='6а',shift=2)],teachers=[planner.Teacher(name='А')],subjects=[planner.Named(name='Математика')],rooms=[planner.Room(name='101')],loads=[planner.Load(id='a',class_name='5а',teacher='А',subject='Математика',room='101',per_week=1),planner.Load(id='b',class_name='6а',teacher='А',subject='Математика',room='101',per_week=1)],placements=[planner.Placement(load_id='a',day='Пн',lesson=1),planner.Placement(load_id='b',day='Пн',lesson=2)])
        summary=planner.teacher_gap_summary(p,schedule);self.assertEqual(summary['total'],1);self.assertEqual(summary['details'],[{'teacher':'А','day':'Пн','gaps':1}])
        result,error=planner.generate(p,schedule);self.assertIsNotNone(result,error);self.assertEqual(planner.teacher_gap_summary(result,schedule)['total'],1)
        schedule['shifts']['1']['Пн'].pop('2');schedule['shifts']['2']['Пн'].pop('1')
        self.assertEqual(planner.teacher_gap_summary(p,schedule)['total'],0) # большая перемена не окно без звонков
        p.placements[1].day='Вт';self.assertEqual(planner.teacher_gap_summary(p,schedule)['total'],0)

    def test_teacher_windows_actual_overlap_and_bound(self):
        self.assertEqual(planner.gaps_in_day([(480,520),(600,640)],[(540,580),(550,570)]),1)
        self.assertEqual(planner.gaps_in_day([(480,520),(600,640)],[(520,540),(540,560),(560,580)]),3)
        p=project();p.loads=p.loads[:1];p.loads[0].per_week=1
        result,error=planner.generate(p,bells(),node_limit=1);self.assertIsNotNone(result,error)

    def test_soft_preferences_scope_search_and_fallback(self):
        p=planner.Project(classes=[planner.SchoolClass(name='5а'),planner.SchoolClass(name='10а')],teachers=[planner.Teacher(name='А')],subjects=[planner.Named(name='Математика')],rooms=[planner.Room(name='101')],loads=[planner.Load(id='a',class_name='5а',teacher='А',subject='Математика',room='101',per_week=1)],preferences=[planner.Preference(scope='grade',scope_value='5',subject='Математика',kind='avoid_lesson',lesson=1)])
        schedule={'shifts':{'1':{'Пн':{'1':{'start':'08:00','end':'08:40'},'2':{'start':'09:00','end':'09:40'}}}}}
        result,error=planner.generate(p,schedule);self.assertIsNotNone(result,error);self.assertEqual(result.placements[0].lesson,2);self.assertFalse(planner.preference_warnings(result))
        schedule['shifts']['1']['Пн'].pop('2');result,error=planner.generate(p,schedule);self.assertIsNotNone(result,error)
        self.assertEqual(result.placements[0].lesson,1);self.assertEqual(len(planner.preference_warnings(result)),1);self.assertFalse(planner.issues(result,schedule,complete=True))
        p.preferences[0].enabled=False;result,error=planner.generate(p,schedule);self.assertIsNotNone(result,error);self.assertFalse(planner.preference_warnings(result))
        p.preferences[0].enabled=True;p.loads[0].class_name='10а';result,error=planner.generate(p,schedule);self.assertIsNotNone(result,error);self.assertFalse(planner.preference_warnings(result))
        p.preferences[0].scope='class';p.preferences[0].scope_value='10а';result,error=planner.generate(p,schedule);self.assertIsNotNone(result,error);self.assertEqual(len(planner.preference_warnings(result)),1)

    def test_publish_allows_soft_preference_violations(self):
        old=copy.deepcopy(backend.state)
        try:
            p=project();p.loads=p.loads[:1];p.loads[0].per_week=1;p.placements=[planner.Placement(load_id='a',day='Пн',lesson=1)]
            p.preferences=[planner.Preference(scope='class',scope_value='5а',subject='Математика',kind='avoid_lesson',lesson=1)]
            backend.state['planner']=p.model_dump();backend.state['bell_schedule']=bells()
            with patch.object(backend,'_save_state'):
                self.assertEqual(len(planner.preference_warnings(p)),1)
                backend.planner_publish(backend.PlannerAction(revision=0))
                self.assertEqual(backend.state['subjects']['grid']['Пн']['1']['5а']['names'],['Математика'])
        finally:backend.state.clear();backend.state.update(old)

    def test_soft_before_detects_both_orders_and_across_groups(self):
        p=planner.Project(classes=[planner.SchoolClass(name='5а')],teachers=[planner.Teacher(name='А'),planner.Teacher(name='Б')],subjects=[planner.Named(name='Физкультура'),planner.Named(name='Физика')],rooms=[planner.Room(name='101'),planner.Room(name='102')],loads=[planner.Load(id='sport',class_name='5а',teacher='А',subject='Физкультура',room='101',group='1 группа',per_week=1),planner.Load(id='physics',class_name='5а',teacher='Б',subject='Физика',room='102',per_week=1)],preferences=[planner.Preference(scope='grade',scope_value='5',subject='Физкультура',kind='avoid_before',next_subject='Физика')])
        p.placements=[planner.Placement(load_id='physics',day='Пн',lesson=2),planner.Placement(load_id='sport',day='Пн',lesson=1)]
        self.assertEqual(len(planner.preference_warnings(p)),1)
        p.placements.reverse();self.assertEqual(len(planner.preference_warnings(p)),1)
        p.placements[1].day='Вт';self.assertFalse(planner.preference_warnings(p))
        p.placements=[];generated,error=planner.generate(p,bells());self.assertIsNotNone(generated,error);self.assertFalse(planner.preference_warnings(generated))

    def test_preference_validation_and_rename_preserves_rules(self):
        old=copy.deepcopy(backend.state)
        with tempfile.TemporaryDirectory() as folder:
            store=staff.Store(Path(folder)/'staff.sqlite3');store.init()
            try:
                p=project();p.preferences=[planner.Preference(scope='class',scope_value='5а',subject='Математика',kind='avoid_lesson',lesson=1),planner.Preference(scope='grade',scope_value='5',subject='Математика',kind='avoid_before',next_subject='Математика')]
                backend.state['planner']=p.model_dump()
                with patch.object(backend,'staff_store',store),patch.object(backend,'_save_state'):
                    r=backend.planner_rename('classes',backend.PlannerRename(revision=0,old_name='5а',new_name='5б'))
                    self.assertEqual(r['project']['preferences'][0]['scope_value'],'5б')
                    r=backend.planner_rename('subjects',backend.PlannerRename(revision=1,old_name='Математика',new_name='Алгебра'))
                    self.assertEqual(r['project']['preferences'][1]['next_subject'],'Алгебра')
                    p=planner.Project.model_validate(r['project']);p.subjects=[];self.assertTrue(any('Предпочтение' in x for x in planner.references(p)))
                with self.assertRaises(ValueError):planner.Preference(scope='grade',scope_value='55',subject='Математика',kind='avoid_lesson',lesson=1)
            finally:backend.state.clear();backend.state.update(old)

    def test_room_unavailability_cross_shift_generator_and_manual_checks(self):
        p=planner.Project(classes=[planner.SchoolClass(name='5а',shift=2)],teachers=[planner.Teacher(name='Учитель',preferred_room='101')],subjects=[planner.Named(name='Физика')],rooms=[planner.Room(name='101',unavailable=[planner.Slot(day='Пн',shift=1,lesson=1)]),planner.Room(name='102')],loads=[planner.Load(id='a',class_name='5а',teacher='Учитель',subject='Физика',room='',per_week=1)])
        schedule={'shifts':{'1':{'Пн':{'1':{'start':'08:00','end':'08:40'}}},'2':{'Пн':{'1':{'start':'08:20','end':'09:00'}}}}}
        generated,error=planner.generate(p,schedule);self.assertIsNotNone(generated,error)
        self.assertEqual(generated.placements[0].room,'102');self.assertFalse(planner.issues(generated,schedule))
        generated.placements[0].room='101';self.assertTrue(any('кабинет 101 недоступен' in x for x in planner.issues(generated,schedule)))
        p.loads[0].room='101';generated,error=planner.generate(p,schedule);self.assertIsNone(generated)
        p.rooms[0].unavailable=[];generated,error=planner.generate(p,schedule);self.assertIsNotNone(generated,error)
        p.rooms[0].unavailable=[planner.Slot(day='Вт',shift=1,lesson=1)]
        self.assertTrue(any('нет звонков для недоступного времени' in x for x in planner.issues(p,schedule)))
        self.assertIsNone(planner.generate(p,schedule)[0])
        with self.assertRaises(ValueError):planner.Room(name='101',unavailable=[{'day':'Пн','shift':1,'lesson':1},{'day':'Пн','shift':1,'lesson':1}])

    def test_room_rules_save_rename_and_map_move(self):
        old=copy.deepcopy(backend.state)
        with tempfile.TemporaryDirectory() as folder:
            store=staff.Store(Path(folder)/'staff.sqlite3');store.init()
            try:
                p=project();p.placements=[planner.Placement(load_id='a',day='Пн',lesson=1)];backend.state['planner']=p.model_dump();backend.state['bell_schedule']=bells()
                p.rooms[0].unavailable=[planner.Slot(day='Пн',shift=1,lesson=2)]
                with patch.object(backend,'staff_store',store),patch.object(backend,'_save_state'):
                    saved=backend.planner_save(p);self.assertEqual(saved['project']['rooms'][0]['unavailable'][0]['lesson'],2)
                    with self.assertRaises(backend.HTTPException) as conflict:backend.planner_move(backend.PlannerMove(revision=1,index=0,day='Пн',lesson=2))
                    self.assertIn('кабинет 101 недоступен',conflict.exception.detail)
                    renamed=backend.planner_rename('rooms',backend.PlannerRename(revision=1,old_name='101',new_name='103'))
                    self.assertEqual(renamed['project']['rooms'][0]['unavailable'][0]['lesson'],2)
                    modified=backend._planner_project();modified.rooms[0].unavailable=[]
                    backend.planner_save(modified)
                    moved=backend.planner_move(backend.PlannerMove(revision=3,index=0,day='Пн',lesson=2))
                    self.assertEqual(moved['project']['placements'][0]['lesson'],2)
            finally:backend.state.clear();backend.state.update(old)

    def test_preferred_room_autopick_fallback_and_fixed_room(self):
        p=planner.Project(classes=[planner.SchoolClass(name="5а"),planner.SchoolClass(name="6а")],teachers=[planner.Teacher(name="А",preferred_room="101"),planner.Teacher(name="Б",preferred_room="101")],subjects=[planner.Named(name="Математика")],rooms=[planner.Room(name="101"),planner.Room(name="102")],loads=[planner.Load(id="a",class_name="5а",teacher="А",subject="Математика",room="",per_week=1),planner.Load(id="b",class_name="6а",teacher="Б",subject="Математика",room="",per_week=1)])
        one={"shifts":{"1":{"Пн":{"1":{"start":"08:00","end":"08:40"}}}}}
        result,error=planner.generate(p,one);self.assertIsNotNone(result,error)
        placements={x.load_id:x for x in result.placements}
        self.assertEqual(placements['a'].room,'101');self.assertEqual(placements['b'].room,'102')
        self.assertFalse(planner.issues(result,one,complete=True))
        teachers,subjects=planner.public_grids(result)
        self.assertEqual(teachers['grid']['Пн']['1']['6а']['rooms'],['102'])
        self.assertEqual(subjects['grid']['Пн']['1']['6а']['groups'][0]['room'],'102')
        self.assertFalse(p.placements)
        p.loads[0].room='102';result,error=planner.generate(p,one);self.assertIsNotNone(result,error)
        placements={x.load_id:x for x in result.placements}
        self.assertEqual(placements['a'].room,'');self.assertEqual(placements['b'].room,'101')
        p.rooms=[planner.Room(name='101')];p.loads[0].room='';result,error=planner.generate(p,one);self.assertIsNone(result)
        self.assertIn('Не удалось',error)

    def test_preferred_room_references_and_rename(self):
        old=copy.deepcopy(backend.state)
        with tempfile.TemporaryDirectory() as folder:
            store=staff.Store(Path(folder)/'staff.sqlite3');store.init()
            try:
                p=project();p.teachers[0].preferred_room='101';p.loads[0].room='';p.placements=[planner.Placement(load_id='a',day='Пн',lesson=1,room='101')]
                self.assertFalse(planner.issues(p,bells()))
                backend.state['planner']=p.model_dump()
                with patch.object(backend,'staff_store',store),patch.object(backend,'_save_state'):
                    r=backend.planner_rename('rooms',backend.PlannerRename(revision=0,old_name='101',new_name='103'))['project']
                    self.assertEqual(r['teachers'][0]['preferred_room'],'103');self.assertEqual(r['placements'][0]['room'],'103')
                    p=planner.Project.model_validate(r);p.rooms=[x for x in p.rooms if x.name!='103']
                    self.assertTrue(any('приоритетный кабинет' in x for x in planner.references(p)))
                    self.assertTrue(any('Урок' in x and 'кабинет' in x for x in planner.references(p)))
            finally:backend.state.clear();backend.state.update(old)

    def test_missing_room_only_for_placed_lesson(self):
        p=project();p.loads[0].room='';self.assertFalse(planner.issues(p,bells()))
        p.placements=[planner.Placement(load_id='a',day='Пн',lesson=1)]
        self.assertTrue(any('не указан кабинет' in e for e in planner.issues(p,bells())))
        p.placements[0].room='101';self.assertFalse(planner.issues(p,bells()))

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

    def test_published_schedule_map_moves_edits_publishes_and_detects_stale(self):
        old=copy.deepcopy(backend.state)
        try:
            classes=["5а","6а"]
            def cell(names,rooms):return {"names":names,"raw":", ".join(names),"rooms":rooms}
            backend.state["teachers"]={"classes":classes,"grid":{"Пн":{"1":{"5а":cell(["Иванов ИИ","Петров ПП"],["101","102"]),"6а":cell(["Другой"],["103"])}}},"numbering":"local"}
            backend.state["subjects"]={"classes":classes,"grid":{"Пн":{"1":{"5а":cell(["Физика","Математика"],["101","102"]),"6а":cell(["Химия"],["103"])}}},"numbering":"local"}
            backend.state["second_shift_classes"]=[];backend.state["bell_schedule"]=bells();backend.state["schedule_map_draft"]=None
            with patch.object(backend,"_save_state"):
                data=backend.read_schedule_map("5а")
                self.assertEqual(len(data["entries"]),1);self.assertFalse(data["has_changes"])
                request=backend.MapMove(revision=0,class_name="5а",day="Пн",raw="1",target_day="Пн",target_lesson=2)
                backend.move_schedule_map(request)
                self.assertEqual(backend.state["teachers"]["grid"]["Пн"]["1"]["5а"]["names"],["Иванов ИИ","Петров ПП"])
                data=backend.read_schedule_map("5а");self.assertTrue(data["has_changes"]);self.assertEqual(data["entries"][0]["lesson"],2)
                self.assertEqual(data["entries"][0]["subjects"]["names"],["Физика","Математика"])
                with self.assertRaises(backend.HTTPException):backend.move_schedule_map(request)
                edit=backend.MapEdit(revision=1,class_name="5а",day="Пн",raw="2",teachers=["Иванов ИИ","Петров ПП"],subjects=["Физика","Алгебра"],rooms=["101","102"])
                backend.edit_schedule_map(edit)
                backend.publish_schedule_map(backend.MapPublish(revision=2))
                self.assertEqual(backend.state["subjects"]["grid"]["Пн"]["2"]["5а"]["names"],["Физика","Алгебра"])
                self.assertFalse(backend.read_schedule_map("5а")["has_changes"])
                backend.move_schedule_map(backend.MapMove(revision=0,class_name="5а",day="Пн",raw="2",target_day="Вт",target_lesson=1))
                backend.state["teachers"]["extra"]="external update"
                self.assertTrue(backend.read_schedule_map("5а")["stale"])
                with self.assertRaises(backend.HTTPException):backend.publish_schedule_map(backend.MapPublish(revision=1))
                backend.reset_schedule_map(backend.MapPublish(revision=1));self.assertFalse(backend.read_schedule_map("5а")["stale"])
        finally:
            backend.state.clear();backend.state.update(old)

    def test_published_schedule_map_global_second_shift_and_conflicts(self):
        import schedule_map
        data={"teachers":{"classes":["5а","6а"],"grid":{"Пн":{"7":{"6а":{"names":["Иванов ИИ"],"rooms":["101"]}},"1":{"5а":{"names":["Иванов И.И."],"rooms":["101"]}}}}},"subjects":{"classes":["5а","6а"],"grid":{}},"second_shift_classes":["6а"],"bell_schedule":{"shifts":{"1":{"Пн":{"1":{"start":"08:00","end":"08:40"},"7":{"start":"13:45","end":"14:25"}}},"2":{"Пн":{"1":{"start":"13:45","end":"14:25"}}}}}}
        self.assertTrue(schedule_map.global_grid(data,"6а"));self.assertEqual(schedule_map.entries(data,"6а")[0]["lesson"],1);self.assertEqual(schedule_map.destination(data,"6а","Пн",1),"7")
        with self.assertRaises(backend.HTTPException) as conflict:backend.check_map_conflicts(data,"6а","Пн",1,1,{"names":["Иванов ИИ"],"rooms":[]},{})
        self.assertEqual(conflict.exception.status_code,409)

    def test_map_move_checks_conflicts_groups_and_revision(self):
        old=copy.deepcopy(backend.state)
        try:
            p=project();p.classes=p.classes[:1]
            p.loads=[planner.Load(id="g1",class_name="5а",subject="Математика",teacher="Учитель",room="101",per_week=2,max_per_day=2,group="1"),planner.Load(id="g2",class_name="5а",subject="Математика",teacher="Другой",room="102",per_week=2,max_per_day=2,group="2")]
            p.placements=[planner.Placement(load_id="g1",day="Пн",lesson=1),planner.Placement(load_id="g2",day="Пн",lesson=2)]
            backend.state["planner"]=p.model_dump();backend.state["bell_schedule"]=bells()
            with patch.object(backend,"_save_state") as save:
                result=backend.planner_move(backend.PlannerMove(revision=0,index=1,day="Пн",lesson=1))
                self.assertEqual(result["project"]["placements"][1]["lesson"],1)
                self.assertEqual(result["project"]["revision"],1)
                with self.assertRaises(backend.HTTPException) as stale:backend.planner_move(backend.PlannerMove(revision=0,index=1,day="Пн",lesson=2))
                self.assertEqual(stale.exception.status_code,409)
                with self.assertRaises(backend.HTTPException) as missing:backend.planner_move(backend.PlannerMove(revision=1,index=3,day="Пн",lesson=2))
                self.assertEqual(missing.exception.status_code,404)
                with self.assertRaises(backend.HTTPException) as bells_error:backend.planner_move(backend.PlannerMove(revision=1,index=1,day="Пн",lesson=12))
                self.assertEqual(bells_error.exception.status_code,422)
                self.assertEqual(save.call_count,1)
                current=backend._planner_project();current.loads[1].teacher="Учитель";current.placements[1].lesson=2;backend.state["planner"]=current.model_dump()
                with self.assertRaises(backend.HTTPException) as conflict:backend.planner_move(backend.PlannerMove(revision=1,index=1,day="Пн",lesson=1))
                self.assertIn("учитель",conflict.exception.detail)
                self.assertEqual(backend._planner_project().placements[1].lesson,2)
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
                self.assertEqual(generated["teacher_gaps"]["total"],planner.teacher_gap_summary(planner.Project.model_validate(generated["project"]),bells())["total"])
                backend.planner_publish(backend.PlannerAction(revision=generated["project"]["revision"]))
                self.assertEqual(backend.state["second_shift_classes"], ["6а"])
                self.assertEqual(backend.state["subjects"]["numbering"], "local")
        finally:
            backend.state.clear()
            backend.state.update(original)


if __name__ == "__main__":
    unittest.main()
