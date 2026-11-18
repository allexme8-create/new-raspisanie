import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import app, planner


def cell(names, groups=None):
    result={'raw':', '.join(names),'names':names,'rooms':['101']}
    if groups is not None:result['groups']=copy.deepcopy(groups)
    return result


class ScheduleLoadImportTests(unittest.TestCase):
    def setUp(self):
        self.old=copy.deepcopy(app.state)
        app.state['planner']=planner.Project(classes=[planner.SchoolClass(name='5а')],teachers=[planner.Teacher(name='Иванов И.И.')],subjects=[planner.Named(name='Математика')],loads=[planner.Load(id='existing',class_name='5а',teacher='Иванов И.И.',subject='Математика',room='',per_week=8)]).model_dump()
        app.state['second_shift_classes']=['6а'];app.state['bell_schedule']=None;app.state['schedule_map_draft']=None
        records=[{'group':'1 группа','teacher':'Сидоров С.С.','subject':'Физика','room':'102'},{'group':'2 группа','teacher':'Кузнецов К.К.','subject':'Химия','room':'103'}]
        app.state['teachers']={'classes':['5а','6а'],'numbering':'local','grid':{'Пн':{'1':{'5а':cell(['Иванов ИИ']),'6а':cell(['Сидоров С.С.','Кузнецов К.К.'],records)},'2':{'5а':cell(['Петров ПП','Орлова ОО'])},'3':{'5а':cell(['Петров ПП','Орлова ОО'])},'4':{'5а':cell(['Петров ПП','Орлова ОО'])}},'Вт':{'1':{'5а':cell(['Иванов ИИ'])},'2':{'5а':cell(['Петров ПП'])}}}}
        app.state['subjects']={'classes':['5а','6а'],'numbering':'local','grid':{'Пн':{'1':{'5а':cell(['Математика']),'6а':cell(['Физика','Химия'],records)},'2':{'5а':cell(['Английский'])},'3':{'5а':cell(['Английский'])},'4':{'5а':cell(['Физика','Химия'])}},'Вт':{'1':{'5а':cell(['Математика'])},'2':{'5а':cell(['Английский'])}}}}
        app.state['dated_schedule_changes']=[{'class_name':'5а','source_date':'2026-01-01'}]
        self.save=patch.object(app,'_save_state');self.save.start();self.client=TestClient(app.app);self.headers={'Authorization':'Bearer '+app._create_token()}
    def tearDown(self):
        self.client.close();self.save.stop();app.state.clear();app.state.update(self.old)
    def preview(self):return self.client.get('/api/admin/planner/schedule-load/preview',headers=self.headers)
    def test_preview_apply_idempotency_and_safe_merging(self):
        self.assertEqual(self.client.get('/api/admin/planner/schedule-load/preview').status_code,401)
        p=self.preview();self.assertEqual(p.status_code,200,p.text);data=p.json()
        self.assertEqual(len(data['duplicates']),1);self.assertEqual(data['duplicates'][0]['per_week'],2)
        self.assertEqual(len(data['skipped']),1);self.assertIn('без данных групп',data['skipped'][0])
        rows=data['rows'];self.assertEqual(len(rows),4)
        inferred=[r for r in rows if r['inferred']];self.assertEqual(len(inferred),2)
        counts={r['teacher']:(r['group'],r['per_week'],r['max_per_day']) for r in inferred}
        self.assertEqual(counts['Петров П.П.'],('2 группа',3,2));self.assertEqual(counts['Орлова О.О.'],('1 группа',2,2))
        original=copy.deepcopy(app.state['teachers']);body={'revision':data['revision'],'schedule_fingerprint':data['schedule_fingerprint']}
        a=self.client.post('/api/admin/planner/schedule-load/apply',headers=self.headers,json=body);self.assertEqual(a.status_code,200,a.text)
        project=a.json()['project'];self.assertEqual(a.json()['added'],4);self.assertEqual(len(project['loads']),5);self.assertEqual(project['loads'][0]['per_week'],8)
        self.assertTrue(all(not load['room'] for load in project['loads']));self.assertEqual(project['placements'],[]);self.assertEqual(app.state['teachers'],original)
        self.assertEqual(next(c['shift'] for c in project['classes'] if c['name']=='6а'),2)
        self.assertTrue(any(g['inferred'] and g['class_name']=='5а' for g in project['groups']))
        self.assertTrue(any(not g['inferred'] and g['class_name']=='6а' for g in project['groups']))
        self.assertEqual(self.client.post('/api/admin/planner/schedule-load/apply',headers=self.headers,json=body).status_code,409)
        p=self.preview().json();self.assertEqual(len(p['rows']),0);self.assertEqual(len(p['duplicates']),5)
    def test_race_and_ambiguous_group_not_added(self):
        data=self.preview().json();before=copy.deepcopy(app.state['planner']);app.state['subjects']['grid']['Пн']['1']['5а']['names']=['Геометрия']
        response=self.client.post('/api/admin/planner/schedule-load/apply',headers=self.headers,json={'revision':data['revision'],'schedule_fingerprint':data['schedule_fingerprint']})
        self.assertEqual(response.status_code,409);self.assertEqual(app.state['planner'],before)
    def test_existing_ungrouped_load_prevents_guessing_over_it(self):
        app.state['planner']['loads'].append(planner.Load(id='manual',class_name='5а',teacher='Петров П.П.',subject='Английский',room='',per_week=6).model_dump())
        data=self.preview().json();self.assertFalse(any(r['teacher']=='Петров П.П.' for r in data['rows']));self.assertTrue(any('несовместимым разделением' in s for s in data['skipped']))

if __name__=='__main__':unittest.main()
