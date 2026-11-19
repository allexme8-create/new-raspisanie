import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import app,planner

class ClearDepartmentLoadTests(unittest.TestCase):
    def setUp(self):
        self.old=copy.deepcopy(app.state)
        teachers=[planner.Teacher(name='А',departments=['Математика','Филология']),planner.Teacher(name='Б',departments=['Математика']),planner.Teacher(name='В',departments=['Филология']),planner.Teacher(name='Г')]
        loads=[planner.Load(id=str(i),teacher=name,class_name='5а',subject=subject,room='',per_week=1) for i,(name,subject) in enumerate([('А','Русский'),('А','Физика'),('Б','Русский'),('В','Русский'),('Г','Физика')])]
        app.state['planner']=planner.Project(teachers=teachers,classes=[planner.SchoolClass(name='5а')],subjects=[planner.Named(name='Русский'),planner.Named(name='Физика')],loads=loads).model_dump()
        self.save_patch=patch.object(app,'_save_state');self.save=self.save_patch.start();self.client=TestClient(app.app);self.auth={'Authorization':'Bearer '+app._create_token()};self.body={'revision':0,'department':'Математика'}
    def tearDown(self):self.client.close();self.save_patch.stop();app.state.clear();app.state.update(self.old)
    def post(self,body=None):return self.client.post('/api/admin/planner/department-load/clear',headers=self.auth,json=body or self.body)
    def test_clear_and_repeat_noop(self):
        before=copy.deepcopy(app.state);self.assertEqual(self.client.post('/api/admin/planner/department-load/clear',json=self.body).status_code,401)
        response=self.post();self.assertEqual(response.status_code,200,response.text);data=response.json();self.assertEqual(data['removed'],3);self.assertEqual([x['id'] for x in data['project']['loads']],['3','4']);self.assertEqual(data['project']['teachers'],before['planner']['teachers']);self.assertEqual(app.state['teachers'],before['teachers']);self.assertEqual(app.state['subjects'],before['subjects']);self.assertEqual(data['project']['revision'],1)
        self.assertEqual(self.post().status_code,409);response=self.post({'revision':1,'department':'Математика'});self.assertEqual(response.status_code,200);self.assertEqual(response.json()['removed'],0);self.assertEqual(response.json()['project']['revision'],1);self.assertEqual(self.save.call_count,1)
    def test_placed_anywhere_blocks_all(self):
        app.state['planner']['placements']=[{'load_id':'1','day':'Пн','lesson':1,'room':''}];before=copy.deepcopy(app.state['planner']);r=self.post();self.assertEqual(r.status_code,409);self.assertIn('расставлено уроков',r.text);self.assertEqual(app.state['planner'],before);self.assertEqual(self.save.call_count,0)
        self.assertEqual(self.post({'revision':0,'department':'__none__'}).status_code,422);self.assertEqual(app.state['planner'],before)
    def test_placement_in_other_department_does_not_block(self):
        app.state['planner']['placements']=[{'load_id':'3','day':'Пн','lesson':1,'room':''}];r=self.post();self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['project']['placements'][0]['load_id'],'3')

if __name__=='__main__':unittest.main()
