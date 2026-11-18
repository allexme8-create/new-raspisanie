import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import app,planner

class TeacherLoadAddTests(unittest.TestCase):
    def setUp(self):
        self.old=copy.deepcopy(app.state)
        app.state['planner']=planner.Project(classes=[planner.SchoolClass(name='5а'),planner.SchoolClass(name='5б')],teachers=[planner.Teacher(name='Учитель А.А.'),planner.Teacher(name='Учитель Б.Б.')],subjects=[planner.Named(name='Математика')],rooms=[planner.Room(name='101')],groups=[planner.ClassGroup(name='1 группа',class_name='5а'),planner.ClassGroup(name='2 группа',class_name='5а')],loads=[planner.Load(id='old',teacher='Учитель А.А.',class_name='5а',subject='Математика',group='1 группа',room='',per_week=3)],placements=[planner.Placement(load_id='old',day='Пн',lesson=1,room='101')]).model_dump()
        self.save=patch.object(app,'_save_state');self.save.start();self.client=TestClient(app.app);self.auth={'Authorization':'Bearer '+app._create_token()}
        self.body={'revision':0,'teacher':'Учитель Б.Б.','class_name':'5а','subject':'Математика','group':'2 группа','room':'101','per_week':4,'max_per_day':2}
    def tearDown(self):self.client.close();self.save.stop();app.state.clear();app.state.update(self.old)
    def post(self,body=None):return self.client.post('/api/admin/planner/teacher-load-add',headers=self.auth,json=body or self.body)
    def test_add_without_changing_existing_placements_and_revision(self):
        self.assertEqual(self.client.post('/api/admin/planner/teacher-load-add',json=self.body).status_code,401)
        before=copy.deepcopy(app.state['planner']);r=self.post();self.assertEqual(r.status_code,200,r.text);p=r.json()['project']
        self.assertEqual(p['loads'][0],before['loads'][0]);self.assertEqual(p['placements'],before['placements']);self.assertEqual(p['loads'][1]['per_week'],4);self.assertEqual(p['loads'][1]['teacher'],'Учитель Б.Б.');self.assertEqual(p['loads'][1]['group'],'2 группа')
        self.assertEqual(self.post().status_code,409)
        b={**self.body,'revision':1};self.assertEqual(self.post(b).status_code,409)
    def test_simple_add_defaults_to_unrestricted_day_and_no_fixed_room(self):
        body={k:v for k,v in self.body.items() if k not in ('max_per_day','room')}
        r=self.post(body);self.assertEqual(r.status_code,200,r.text)
        load=r.json()['project']['loads'][-1];self.assertEqual(load['max_per_day'],12);self.assertEqual(load['room'],'')
    def test_edit_without_daily_field_preserves_existing_setting(self):
        body={'revision':0,'load_id':'old','class_name':'5а','teacher':'Учитель А.А.','subject':'Математика','group':'1 группа','room':'','per_week':3}
        r=self.client.post('/api/admin/planner/load-change',headers=self.auth,json=body);self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['project']['loads'][0]['max_per_day'],1);self.assertEqual(r.json()['project']['placements'][0]['room'],'101')
    def test_invalid_and_ambiguous_group_are_atomic(self):
        before=copy.deepcopy(app.state['planner'])
        for changes,status in [({'group':''},409),({'group':'1 группа'},409),({'group':'нет'},422),({'class_name':'нет'},422),({'teacher':'нет'},422),({'per_week':0},422),({'room':'нет'},422),({'max_per_day':13},422)]:
            r=self.post({**self.body,**changes});self.assertEqual(r.status_code,status,r.text);self.assertEqual(app.state['planner'],before)
        app.state['planner']['loads'][0]['group']='';self.assertEqual(self.post().status_code,409)
    def test_delete_is_atomic_and_preserves_other_entries(self):
        body={'revision':0,'load_id':'old'};before=copy.deepcopy(app.state['planner'])
        self.assertEqual(self.client.post('/api/admin/planner/teacher-load-delete',json=body).status_code,401)
        r=self.client.post('/api/admin/planner/teacher-load-delete',headers=self.auth,json=body);self.assertEqual(r.status_code,409);self.assertEqual(app.state['planner'],before)
        added=self.post().json()['project']['loads'][1]
        body={'revision':1,'load_id':added['id']};r=self.client.post('/api/admin/planner/teacher-load-delete',headers=self.auth,json=body)
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['project']['loads'],before['loads']);self.assertEqual(r.json()['project']['placements'],before['placements'])
        self.assertEqual(self.client.post('/api/admin/planner/teacher-load-delete',headers=self.auth,json=body).status_code,409)
        body['revision']=2;self.assertEqual(self.client.post('/api/admin/planner/teacher-load-delete',headers=self.auth,json=body).status_code,404)

    def test_edit_class_and_hours_then_reject_when_placed(self):
        added=self.post().json()['project']['loads'][1]
        change={'revision':1,'load_id':added['id'],'teacher':added['teacher'],'class_name':'5б','subject':added['subject'],'group':'','room':'','per_week':6,'max_per_day':2}
        r=self.client.post('/api/admin/planner/load-change',headers=self.auth,json=change);self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['project']['loads'][1]['class_name'],'5б');self.assertEqual(r.json()['project']['loads'][1]['per_week'],6)
        app.state['planner']['placements'].append({'load_id':added['id'],'day':'Вт','lesson':1,'room':'101'})
        change['revision']=2;change['per_week']=7;before=copy.deepcopy(app.state['planner']);r=self.client.post('/api/admin/planner/load-change',headers=self.auth,json=change);self.assertEqual(r.status_code,409);self.assertEqual(app.state['planner'],before)

if __name__=='__main__':unittest.main()
