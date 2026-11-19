import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import app,planner

class VacanciesDepartmentsTests(unittest.TestCase):
    def setUp(self):
        self.old=copy.deepcopy(app.state)
        app.state['planner']=planner.Project(classes=[planner.SchoolClass(name='5а')],teachers=[planner.Teacher(name='Учитель А.А.',departments=['Математика'])],subjects=[planner.Named(name='Физика')],rooms=[planner.Room(name='101')]).model_dump()
        self.save=patch.object(app,'_save_state');self.save.start();self.client=TestClient(app.app);self.auth={'Authorization':'Bearer '+app._create_token()}
    def tearDown(self):self.client.close();self.save.stop();app.state.clear();app.state.update(self.old)
    def post(self,path,body):return self.client.post('/api/admin/planner/'+path,headers=self.auth,json=body)
    def test_catalog_change_and_assigned_delete(self):
        p=app._planner_project();self.assertIn('Вакансия',[x.name for x in p.departments])
        r=self.post('department-catalog',{'revision':0,'action':'add','new_name':'История'});self.assertEqual(r.status_code,200,r.text);self.assertIn('История',[x['name'] for x in r.json()['project']['departments']])
        r=self.post('department-catalog',{'revision':1,'action':'rename','name':'Математика','new_name':'Математические науки'});self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['project']['teachers'][0]['departments'],['Математические науки'])
        before=copy.deepcopy(app.state['planner']);r=self.post('department-catalog',{'revision':2,'action':'delete','name':'Математические науки'});self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['project']['teachers'][0]['departments'],['Вакансия']);self.assertEqual(r.json()['project']['loads'],before['loads'])
        self.assertEqual(self.post('department-catalog',{'revision':3,'action':'add','new_name':'история'}).status_code,409)
        r=self.post('department-catalog',{'revision':3,'action':'delete','name':'История'});self.assertEqual(r.status_code,200);self.assertNotIn('История',[x['name'] for x in r.json()['project']['departments']]);self.assertEqual(self.post('department-catalog',{'revision':3,'action':'delete','name':'Филология'}).status_code,409)
        self.assertEqual(self.post('teacher-departments',{'revision':4,'teacher':'Учитель А.А.','departments':['Неизвестная']}).status_code,422)
    def test_vacancy_load_and_safe_assignment(self):
        body={'revision':0,'teacher':'Вакансия','vacancy':True,'class_name':'5а','subject':'Физика','per_week':3}
        r=self.post('teacher-load-add',body);self.assertEqual(r.status_code,200,r.text);project=r.json()['project'];vacancy=next(t for t in project['teachers'] if t['is_vacancy']);self.assertEqual(vacancy['departments'],['Вакансия']);load=project['loads'][0];self.assertEqual(load['teacher'],vacancy['name']);self.assertIn('назначьте учителя', ' '.join(r.json()['issues']))
        generated=self.post('generate',{'revision':1});self.assertEqual(generated.status_code,422);self.assertIn('ваканси',generated.text)
        published=self.post('publish',{'revision':1});self.assertEqual(published.status_code,422)
        candidate=copy.deepcopy(project);candidate['placements']=[{'load_id':load['id'],'day':'Пн','lesson':1,'room':'101'}]
        self.assertEqual(self.client.put('/api/admin/planner',headers=self.auth,json=candidate).status_code,422);self.assertEqual(app.state['planner'],project)
        assign={'revision':1,'load_id':load['id'],'teacher':'Учитель А.А.','room':'','group':''};r=self.post('load-change',assign);self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['project']['loads'][0]['teacher'],'Учитель А.А.');self.assertFalse(any('ваканси' in e for e in r.json()['issues']))
    def test_renamed_vacancy_department_and_parallel_groups(self):
        r=self.post('department-catalog',{'revision':0,'action':'rename','name':'Вакансия','new_name':'Свободные ставки'});self.assertEqual(r.status_code,200,r.text)
        app.state['planner']['groups']=[{'class_name':'5а','name':'1 группа','inferred':False},{'class_name':'5а','name':'2 группа','inferred':False}]
        body={'revision':1,'teacher':'Вакансия','vacancy':True,'class_name':'5а','subject':'Физика','per_week':2,'group':'1 группа'}
        r=self.post('teacher-load-add',body);self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['project']['teachers'][-1]['departments'],['Свободные ставки'])
        body['revision']=2;body['group']='2 группа';r=self.post('teacher-load-add',body);self.assertEqual(r.status_code,200,r.text);self.assertEqual(len(r.json()['project']['loads']),2)
        body['revision']=3;self.assertEqual(self.post('teacher-load-add',body).status_code,409)
        before=copy.deepcopy(app.state['planner']);r=self.post('department-catalog',{'revision':3,'action':'delete','name':'Свободные ставки'});self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['project']['loads'],before['loads']);self.assertEqual(r.json()['project']['teachers'][-1]['departments'],[])

    def test_custom_department_can_be_selected_for_new_teacher(self):
        self.post('department-catalog',{'revision':0,'action':'add','new_name':'Новая'});
        body={'revision':1,'teacher':'Новый НН','create_teacher':True,'department':'Новая','class_name':'5а','subject':'Физика','per_week':2}
        r=self.post('teacher-load-add',body);self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['project']['teachers'][-1]['departments'],['Новая'])

if __name__=='__main__':unittest.main()
