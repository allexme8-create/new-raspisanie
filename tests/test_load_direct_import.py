import copy,sys,unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import app,planner

def csv(rows):return ('ФИО учителя;Предмет;Класс;Часы\n'+'\n'.join(';'.join(map(str,r)) for r in rows)).encode()
class DirectImportTests(unittest.TestCase):
 def setUp(self):
  self.old=copy.deepcopy(app.state);app.state['planner']=planner.Project().model_dump();app.state['second_shift_classes']=['6а'];self.patch=patch.object(app,'_save_state');self.save=self.patch.start();self.client=TestClient(app.app);self.h={'Authorization':'Bearer '+app._create_token()}
 def tearDown(self):self.client.close();self.patch.stop();app.state.clear();app.state.update(self.old)
 def post(self,rows,rev=0,auth=True):return self.client.post('/api/admin/planner/load-import/direct',headers=self.h if auth else {},data={'revision':str(rev)},files={'file':('load.csv',csv(rows),'text/csv')})
 def test_create_and_repeat(self):
  rows=[('Иванов ИИ','Русский','5а',3),('Петров ПП','Русский','5а',2),('Иванов ИИ','Физика','6а',1)]
  self.assertEqual(self.post(rows,auth=False).status_code,401);r=self.post(rows);self.assertEqual(r.status_code,200,r.text);p=r.json()['project'];self.assertEqual(len(p['loads']),3);self.assertEqual({x['group'] for x in p['loads'] if x['class_name']=='5а'},{'1 группа','2 группа'});self.assertEqual(next(x['shift'] for x in p['classes'] if x['name']=='6а'),2);self.assertIn('Иванов И.И.',[x['name'] for x in p['teachers']]);self.assertEqual(self.post(rows).status_code,409);r=self.post(rows,1);self.assertEqual(r.status_code,200,r.text);self.assertEqual((r.json()['added'],r.json()['updated']),(0,0))
 def test_ambiguity_or_placement_rolls_back(self):
  app.state['planner']=planner.Project(classes=[planner.SchoolClass(name='5а')],teachers=[planner.Teacher(name='Иванов И.И.')],subjects=[planner.Named(name='Математика')],loads=[planner.Load(id='a',class_name='5а',teacher='Иванов И.И.',subject='Математика',room='',per_week=2)],placements=[planner.Placement(load_id='a',day='Пн',lesson=1)]).model_dump();before=copy.deepcopy(app.state['planner'])
  r=self.post([('Иванов ИИ','Математика','5а',3),('Петров ПП','Физика','6а',1)]);self.assertEqual(r.status_code,409,r.text);self.assertEqual(app.state['planner'],before);self.save.assert_not_called()
  r=self.post([('Иванов ИИ','Математик','5а',3)]);self.assertEqual(r.status_code,422,r.text);self.assertIn('похоже',r.text);self.assertEqual(app.state['planner'],before)
