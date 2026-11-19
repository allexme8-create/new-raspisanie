import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import app,planner

class VacancyMembershipTests(unittest.TestCase):
    def setUp(self):
        self.old=copy.deepcopy(app.state)
        app.state['planner']=planner.Project(classes=[planner.SchoolClass(name='5а')],teachers=[planner.Teacher(name='А',departments=[]),planner.Teacher(name='Б',departments=['Математика'])],subjects=[planner.Named(name='Физика'),planner.Named(name='Химия')],loads=[planner.Load(id='l',teacher='А',class_name='5а',subject='Физика',room='',per_week=2)]).model_dump()
        app.state['planner_unassigned_vacancy_migrated']=False
        self.save=patch.object(app,'_save_state');self.mock=self.save.start();self.client=TestClient(app.app);self.auth={'Authorization':'Bearer '+app._create_token()}
    def tearDown(self):self.client.close();self.save.stop();app.state.clear();app.state.update(self.old)
    def test_migration_preserves_teacher_load_and_published_and_runs_once(self):
        before=copy.deepcopy(app.state);app.migrate_unassigned_to_vacancy();p=app._planner_project()
        self.assertEqual(p.teachers[0].departments,['Вакансия']);self.assertFalse(p.teachers[0].is_vacancy);self.assertEqual(p.teachers[1].departments,['Математика']);self.assertEqual(p.loads[0].model_dump(),before['planner']['loads'][0]);self.assertEqual(app.state['teachers'],before['teachers']);self.assertEqual(p.revision,1)
        app.migrate_unassigned_to_vacancy();self.assertEqual(self.mock.call_count,1);self.assertEqual(app._planner_project().revision,1)
    def test_new_teacher_without_department_gets_vacancy_membership_not_vacancy_status(self):
        body={'revision':0,'teacher':'Новый НН','create_teacher':True,'subject':'Химия','class_name':'5а','per_week':1}
        r=self.client.post('/api/admin/planner/teacher-load-add',headers=self.auth,json=body);self.assertEqual(r.status_code,200,r.text);t=r.json()['project']['teachers'][-1];self.assertEqual(t['departments'],['Вакансия']);self.assertFalse(t['is_vacancy'])
    def test_rename_default_then_migrate(self):
        p=app._planner_project();p.departments[-1].name='Резерв';p.vacancy_department='Резерв';app.state['planner']=p.model_dump();app.migrate_unassigned_to_vacancy();self.assertEqual(app._planner_project().teachers[0].departments,['Резерв'])

if __name__=='__main__':unittest.main()
