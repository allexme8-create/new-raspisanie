import copy,sys,unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import app,planner,load_import

def sample():
 rows=[['№','ФИО, учителя','Начальная ступень','','Основная ступень','','Старшая ступень','','Итого'],['','','Предмет/класс','Кол-во часов','Предмет/класс','Кол-во часов','Предмет/класс','Кол-во часов',''],['1','Иванов И.И.','','','информатика/5А','1','информационная безопасность/10Ф','1','2'],['2','','','','информатика 6 А','2','','','2'],['3','','','','3','','1','','4']]
 return ('\n'.join(';'.join(r) for r in rows)).encode('cp1251')

class CombinedFileTests(unittest.TestCase):
 def test_parser_and_direct_import(self):
  rows=load_import.parse(sample(),'load.csv');self.assertEqual(len(rows),3);self.assertEqual((rows[0]['subject'],rows[0]['class_name']),( 'информатика','5А'));self.assertEqual(rows[2]['class_name'],'6 А');self.assertEqual(rows[2]['teacher'],'Иванов И.И.')
  old=copy.deepcopy(app.state)
  try:
   app.state['planner']=planner.Project(classes=[planner.SchoolClass(name='10фм')],teachers=[planner.Teacher(name='Иванов И.И.')],subjects=[planner.Named(name='Информ.безопасность')]).model_dump()
   with patch.object(app,'_save_state'),TestClient(app.app) as c:
    r=c.post('/api/admin/planner/load-import/direct',headers={'Authorization':'Bearer '+app._create_token()},data={'revision':'0'},files={'file':('load.csv',sample())});self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['added'],3);self.assertIn('10Ф',r.json()['created']['class_name']);self.assertTrue(any(l['subject']=='Информ.безопасность' for l in r.json()['project']['loads']))
  finally:app.state.clear();app.state.update(old)
