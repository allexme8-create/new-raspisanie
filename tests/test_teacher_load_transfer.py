import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import app
import planner
from fastapi.testclient import TestClient


def bells():
    return {'shifts':{'1':{'Пн':{'1':{'start':'08:00','end':'08:40'},'2':{'start':'09:00','end':'09:40'}}},'2':{'Пн':{'1':{'start':'08:20','end':'09:00'},'2':{'start':'10:00','end':'10:40'}}}}}


def project():
    return planner.Project(classes=[planner.SchoolClass(name='5а'),planner.SchoolClass(name='6а',shift=2)],teachers=[planner.Teacher(name='Иванова И.И.'),planner.Teacher(name='Петров П.П.')],subjects=[planner.Named(name='Математика'),planner.Named(name='Физика')],rooms=[planner.Room(name='101'),planner.Room(name='102')],loads=[planner.Load(id='a',class_name='5а',teacher='Иванова И.И.',subject='Математика',room='101',per_week=1),planner.Load(id='b',class_name='5а',teacher='Иванова И.И.',subject='Физика',room='101',per_week=1),planner.Load(id='c',class_name='6а',teacher='Петров П.П.',subject='Физика',room='102',per_week=1)],placements=[planner.Placement(load_id='a',day='Пн',lesson=1),planner.Placement(load_id='b',day='Пн',lesson=2),planner.Placement(load_id='c',day='Пн',lesson=2)])


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.old=copy.deepcopy(app.state)
        app.state['planner']=project().model_dump();app.state['bell_schedule']=bells()
        self.save=patch.object(app,'_save_state');self.save.start()
        self.client=TestClient(app.app);self.headers={'Authorization':'Bearer '+app._create_token()}
        self.body={'revision':0,'source':'Иванова И.И.','target':'Петров П.П.'}
    def tearDown(self):
        self.client.close();self.save.stop();app.state.clear();app.state.update(self.old)
    def post(self,body=None):
        return self.client.post('/api/admin/planner/transfer-teacher-load',headers=self.headers,json=body or self.body)
    def test_transfer_preserves_lessons_and_published_schedule(self):
        published=copy.deepcopy(app.state['teachers']);before=copy.deepcopy(app.state['planner']['placements'])
        self.assertEqual(self.client.post('/api/admin/planner/transfer-teacher-load',json=self.body).status_code,401)
        result=self.post();self.assertEqual(result.status_code,200,result.text)
        data=result.json();self.assertEqual((data['transferred'],data['placements']),(2,2));self.assertEqual(data['project']['placements'],before)
        self.assertTrue(all(x['teacher']=='Петров П.П.' for x in data['project']['loads']))
        self.assertEqual(app.state['teachers'],published)
        self.assertEqual(self.post().status_code,409)
    def test_overlap_across_shifts_is_rejected_without_mutation(self):
        app.state['planner']['placements'][2]['lesson']=1
        before=copy.deepcopy(app.state['planner']);result=self.post()
        self.assertEqual(result.status_code,409,result.text);self.assertIn('конфликт',result.text);self.assertEqual(app.state['planner'],before)
    def test_unavailability_and_missing_bells_are_rejected(self):
        app.state['planner']['teachers'][1]['unavailable']=[{'day':'Пн','shift':2,'lesson':1}]
        before=copy.deepcopy(app.state['planner']);result=self.post();self.assertEqual(result.status_code,409,result.text);self.assertEqual(app.state['planner'],before)
        app.state['bell_schedule']['shifts']['2']['Пн'].pop('1')
        result=self.post();self.assertEqual(result.status_code,422,result.text);self.assertEqual(app.state['planner'],before)
    def test_duplicate_workload_same_teacher_and_missing_clock(self):
        app.state['planner']['loads'][2]['class_name']='5а'
        before=copy.deepcopy(app.state['planner']);self.assertEqual(self.post().status_code,409);self.assertEqual(app.state['planner'],before)
        app.state['planner']=project().model_dump();app.state['bell_schedule']=None
        before=copy.deepcopy(app.state['planner']);self.assertEqual(self.post().status_code,422);self.assertEqual(app.state['planner'],before)
        self.assertEqual(self.post({**self.body,'target':self.body['source']}).status_code,422)


class MapTransferTests(unittest.TestCase):
    def setUp(self):
        self.old=copy.deepcopy(app.state)
        app.state['planner']=project().model_dump();app.state['bell_schedule']=bells();app.state['second_shift_classes']=['6а'];app.state['schedule_map_draft']=None;app.state['weekly_move_notices']=[]
        groups=[{'group':'1 группа','teacher':'Иванова И.И.','subject':'Математика','room':'101'},{'group':'2 группа','teacher':'Другой Д.Д.','subject':'Английский','room':'103'}]
        def cell(names,rooms,groups=None):
            result={'names':names,'raw':', '.join(names),'rooms':rooms}
            if groups is not None:result['groups']=copy.deepcopy(groups)
            return result
        app.state['teachers']={'classes':['5а','6а'],'numbering':'local','grid':{'Пн':{'1':{'5а':cell(['Иванова И.И.','Другой Д.Д.'],['101','103'],groups)},'2':{'6а':cell(['Петров П.П.'],['102'])}}}}
        app.state['subjects']={'classes':['5а','6а'],'numbering':'local','grid':{'Пн':{'1':{'5а':cell(['Математика','Английский'],['101','103'],groups)},'2':{'6а':cell(['Физика'],['102'])}}}}
        self.save=patch.object(app,'_save_state');self.save.start();self.client=TestClient(app.app);self.headers={'Authorization':'Bearer '+app._create_token()}
        self.body={'revision':0,'source':'Иванова И.И.','target':'Петров П.П.'}
    def tearDown(self):
        self.client.close();self.save.stop();app.state.clear();app.state.update(self.old)
    def post(self):return self.client.post('/api/admin/schedule-map/transfer-teacher',headers=self.headers,json=self.body)
    def test_transfer_preserves_groups_and_requires_publication(self):
        original=copy.deepcopy(app.state['teachers']);result=self.post();self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['transferred'],1)
        self.assertEqual(app.state['teachers'],original)
        draft=app.state['schedule_map_draft']['data'];t=draft['teachers']['grid']['Пн']['1']['5а'];s=draft['subjects']['grid']['Пн']['1']['5а']
        self.assertEqual(t['names'],['Петров П.П.','Другой Д.Д.']);self.assertEqual(t['groups'][0]['teacher'],'Петров П.П.');self.assertEqual(s['groups'][0]['teacher'],'Петров П.П.');self.assertEqual(t['rooms'],['101','103']);self.assertEqual(s['names'],['Математика','Английский'])
        self.assertEqual(self.post().status_code,409)
        with patch.object(app,'_touch_updated_at'):app.publish_schedule_map(app.MapPublish(revision=1))
        self.assertEqual(app.state['teachers']['grid']['Пн']['1']['5а']['names'][0],'Петров П.П.')
    def test_overlap_and_invalid_targets_leave_draft_unchanged(self):
        app.state['teachers']['grid']['Пн']['1']['6а']=app.state['teachers']['grid']['Пн']['2'].pop('6а')
        app.state['subjects']['grid']['Пн']['1']['6а']=app.state['subjects']['grid']['Пн']['2'].pop('6а')
        result=self.post();self.assertEqual(result.status_code,409,result.text);self.assertIsNone(app.state['schedule_map_draft'])
        self.body['target']='Несуществующий';self.assertEqual(self.post().status_code,422);self.assertIsNone(app.state['schedule_map_draft'])

if __name__=='__main__':unittest.main()
