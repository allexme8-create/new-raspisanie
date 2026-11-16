import copy,sys,tempfile,unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import app
from fastapi.testclient import TestClient

class DatedScheduleTests(unittest.TestCase):
 def setUp(self):
  self.original=copy.deepcopy(app.state)
  def c(names,rooms):return {'names':names,'raw':', '.join(names),'rooms':rooms}
  app.state.update({'teachers':{'classes':['5а','6а'],'numbering':'local','grid':{'Пн':{'1':{'5а':c(['Иванов'],['101']),'6а':c(['Петров'],['102'])}},'Вт':{'1':{'6а':c(['Иванов'],['101'])}}}},'subjects':{'classes':['5а','6а'],'numbering':'local','grid':{'Пн':{'1':{'5а':c(['Физика'],['101']),'6а':c(['Химия'],['102'])}},'Вт':{'1':{'6а':c(['Алгебра'],['101'])}}}},'bell_schedule':{'shifts':{'1':{day:{'1':{'start':'08:00','end':'08:40'},'2':{'start':'09:00','end':'09:40'}} for day in ('Пн','Вт')}}},'second_shift_classes':[],'schedule_map_draft':None,'dated_schedule_changes':[],'dated_schedule_revision':0})
 def tearDown(self):app.state.clear();app.state.update(self.original)
 def test_auth_move_conflict_and_public_notice(self):
  with patch.object(app,'_save_state'),TestClient(app.app) as client:
   headers={'Authorization':'Bearer '+app._create_token()};url='/api/admin/dated-schedule-changes'
   payload={'revision':0,'class_name':'5а','day':'Пн','raw':'1','teacher':'Иванов','source_date':'2026-11-09','target_date':'2026-11-10','target_lesson':1}
   self.assertEqual(client.post(url,json=payload).status_code,401)
   self.assertEqual(client.post(url,headers=headers,json=payload).status_code,409) # teacher and room busy Tuesday
   payload['target_lesson']=2;r=client.post(url,headers=headers,json=payload);self.assertEqual(r.status_code,200,r.text)
   self.assertEqual(r.json()['revision'],1);public=client.get('/api/schedule').json();self.assertEqual(public['dated_changes'][0]['target_lesson'],2)
   self.assertNotIn('cells',public['dated_changes'][0]);self.assertFalse(public['dated_changes'][0]['stale'])
   self.assertEqual(public['teachers']['grid']['Пн']['1']['5а']['names'],['Иванов'])
   self.assertEqual(client.post(url,headers=headers,json=payload).status_code,409)
   self.assertEqual(client.post(url,headers=headers,json={**payload,'revision':1}).status_code,404)
   cid=r.json()['changes'][0]['id'];self.assertEqual(client.delete(url+'/'+cid+'?revision=0',headers=headers).status_code,409)
   self.assertEqual(client.delete(url+'/'+cid+'?revision=1',headers=headers).status_code,200);self.assertEqual(client.get('/api/schedule').json()['dated_changes'],[])
 def test_cancel_stale_weekly_draft_and_wrong_day(self):
  with patch.object(app,'_save_state'):
   request=app.DatedChange(revision=0,class_name='5а',day='Пн',raw='1',teacher='Иванов',source_date=date(2026,11,10))
   with self.assertRaises(app.HTTPException):app.create_dated_change(request)
   request.source_date=date(2026,11,9);app.state['schedule_map_draft']={'revision':1}
   with self.assertRaises(app.HTTPException):app.create_dated_change(request)
   app.state['schedule_map_draft']=None;result=app.create_dated_change(request);self.assertIsNone(result['changes'][0]['target_date'])
   app.state['subjects']['extra']='changed';self.assertTrue(app.public_dated_changes()[0]['stale'])
   self.assertEqual(app.delete_dated_change(result['changes'][0]['id'],1)['changes'],[])
 def test_date_move_enforces_class_restriction_and_reset(self):
  app.state['planner']={'classes':[{'name':'5а','unavailable':[{'day':'Вт','shift':1,'lesson':2}]}]}
  req=app.DatedChange(revision=0,class_name='5а',day='Пн',raw='1',teacher='Иванов',source_date=date(2026,11,9),target_date=date(2026,11,10),target_lesson=2)
  with patch.object(app,'_save_state'):
   with self.assertRaises(app.HTTPException) as error:app.create_dated_change(req)
   self.assertIn('класс 5а недоступен',error.exception.detail)
   req.target_date=None;req.target_lesson=None;app.create_dated_change(req)
   with self.assertRaises(app.HTTPException):app.reset_dated_changes(app.DatedReset(revision=0))
   self.assertEqual(app.reset_dated_changes(app.DatedReset(revision=1))['changes'],[])

 def test_changed_source_group_is_rejected(self):
  app.state['teachers']['grid']['Пн']['1']['5а']['names'].append('Петров')
  with patch.object(app,'_save_state'),self.assertRaises(app.HTTPException):app.create_dated_change(app.DatedChange(revision=0,class_name='5а',day='Пн',raw='1',teacher='Иванов',source_date=date(2026,11,9)))
