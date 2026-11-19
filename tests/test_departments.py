import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import app, departments, planner

class DepartmentsTest(unittest.TestCase):
    def setUp(self):
        self.old=copy.deepcopy(app.state)
        app.state['planner']=planner.Project(teachers=[planner.Teacher(name='Иванов И.И.'),planner.Teacher(name='Петров П.П.',departments=['Математика'])]).model_dump()
        self.save=patch.object(app,'_save_state');self.save.start();self.client=TestClient(app.app);self.auth={'Authorization':'Bearer '+app._create_token()}
    def tearDown(self):
        self.client.close();self.save.stop();app.state.clear();app.state.update(self.old)
    def test_file_preview_and_apply_without_guessing(self):
        csv='№;ФИО, учителя;Предмет\n1;Иванов ИИ;математика\n2;Петроф П.П.;математика\n3;Иванов И.И.;математика\n;Итого;\n4;Новиков Н.Н.;математика\n'
        request=lambda:self.client.post('/api/admin/planner/department-file/preview',headers=self.auth,files={'file':('test.csv',csv.encode('cp1251'),'text/csv')})
        r=request();self.assertEqual(r.status_code,200,r.text);d=r.json();self.assertEqual(len(d['rows']),3);self.assertEqual(d['rows'][0]['match']['value'],'Иванов И.И.');self.assertEqual(d['rows'][1]['match']['value'],'')
        self.assertEqual(self.client.post('/api/admin/planner/department-file/preview',files={'file':('test.csv',csv.encode('cp1251'),'text/csv')}).status_code,401)
        body={'revision':d['revision'],'department':'Филология','rows':[{'source':'Иванов ИИ','teacher':'Иванов И.И.'},{'source':'Петроф П.П.','teacher':'Петров П.П.'},{'source':'Новиков Н.Н.','teacher':''}]}
        applied=self.client.post('/api/admin/planner/department-file/apply',headers=self.auth,json=body);self.assertEqual(applied.status_code,200,applied.text)
        ts={t['name']:t['departments'] for t in applied.json()['project']['teachers']};self.assertEqual(ts['Петров П.П.'],['Математика','Филология']);self.assertEqual(ts['Новиков Н.Н.'],['Филология']);self.assertEqual(applied.json()['assigned'],3)
        self.assertEqual(self.client.post('/api/admin/planner/department-file/apply',headers=self.auth,json=body).status_code,409)
    def test_edit_and_save_preserves_loads_and_conflict(self):
        revision=app._planner_project().revision
        data={'revision':revision,'teacher':'Иванов И.И.','departments':['Математика','Филология']}
        r=self.client.post('/api/admin/planner/teacher-departments',headers=self.auth,json=data);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['project']['teachers'][0]['departments'],['Математика','Филология'])
        self.assertEqual(self.client.post('/api/admin/planner/teacher-departments',headers=self.auth,json=data).status_code,409)
        data['revision']+=1;data['departments']=[];r=self.client.post('/api/admin/planner/teacher-departments',headers=self.auth,json=data);self.assertEqual(r.status_code,200);self.assertEqual(r.json()['project']['teachers'][0]['departments'],['Вакансия'])
        data['revision']+=1;data['departments']=['Иная'];self.assertEqual(self.client.post('/api/admin/planner/teacher-departments',headers=self.auth,json=data).status_code,422)
    def test_foreign_languages_and_all_six_departments(self):
        data={'revision':0,'teacher':'Иванов И.И.','departments':list(departments.NAMES)}
        r=self.client.post('/api/admin/planner/teacher-departments',headers=self.auth,json=data);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['project']['teachers'][0]['departments'],list(departments.NAMES))
        data['revision']=1;data['departments']=['Иностранные языки'];r=self.client.post('/api/admin/planner/teacher-departments',headers=self.auth,json=data);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['project']['teachers'][0]['departments'],['Иностранные языки'])
        body={'revision':2,'department':'Иностранные языки','rows':[{'source':'Петров П.П.','teacher':'Петров П.П.'}]}
        r=self.client.post('/api/admin/planner/department-file/apply',headers=self.auth,json=body);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['project']['teachers'][1]['departments'],['Математика','Иностранные языки'])
    def test_repeated_teacher_is_atomic(self):
        p=copy.deepcopy(app.state['planner']);body={'revision':0,'department':'Математика','rows':[{'source':'А','teacher':'Иванов И.И.'},{'source':'Б','teacher':'Иванов И.И.'}]}
        self.assertEqual(self.client.post('/api/admin/planner/department-file/apply',headers=self.auth,json=body).status_code,422);self.assertEqual(app.state['planner'],p)

if __name__=='__main__':unittest.main()
