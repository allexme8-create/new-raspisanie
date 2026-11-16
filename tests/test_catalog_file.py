import copy,io,sys,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import app,planner,catalog_file
from fastapi.testclient import TestClient
from openpyxl import Workbook

class CatalogFileTests(unittest.TestCase):
 def setUp(self):self.original=copy.deepcopy(app.state);app.state['planner']=planner.Project(teachers=[planner.Teacher(name='Иванов И.И.')],rooms=[planner.Room(name='101')]).model_dump()
 def tearDown(self):app.state.clear();app.state.update(self.original)
 def test_csv_header_and_no_header(self):
  data='№;ФИО, учителя\n1;Иванов ИИ\n2;Петрова АБ\n'.encode('cp1251')
  self.assertEqual(catalog_file.parse(data,'x.csv','teachers'),['Иванов ИИ','Петрова АБ'])
  self.assertEqual(catalog_file.parse('Кабинет\n101\nСпортзал\n'.encode(),'x.csv','rooms'),['101','Спортзал'])
  self.assertEqual(catalog_file.parse('101\n102\n'.encode(),'x.csv','rooms'),['101','102'])
  with self.assertRaises(catalog_file.ParseError):catalog_file.parse('код;данные\n1;123\n'.encode(),'x.csv','rooms')
 def test_xlsx_split_name_and_numeric_rooms(self):
  book=Workbook();ws=book.active;ws.append(['Фамилия','Имя','Отчество']);ws.append(['Петров','Пётр','Ильич']);out=io.BytesIO();book.save(out)
  self.assertEqual(catalog_file.parse(out.getvalue(),'x.xlsx','teachers'),['Петров Пётр Ильич'])
  book=Workbook();ws=book.active;ws.append(['№','Кабинет']);ws.append([1,101]);ws.append([2,'Актовый зал']);out=io.BytesIO();book.save(out)
  self.assertEqual(catalog_file.parse(out.getvalue(),'x.xlsx','rooms'),['101','Актовый зал'])
 def test_ods_and_room_header_variants(self):
  body='<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:spreadsheet><table:table><table:table-row><table:table-cell><text:p>ФИО</text:p></table:table-cell></table:table-row><table:table-row><table:table-cell><text:p>Петров ПП</text:p></table:table-cell></table:table-row></table:table></office:spreadsheet></office:body></office:document-content>'
  out=io.BytesIO()
  with zipfile.ZipFile(out,'w') as archive:archive.writestr('content.xml',body)
  self.assertEqual(catalog_file.parse(out.getvalue(),'test.ods','teachers'),['Петров ПП'])
  self.assertEqual(catalog_file.parse('№ кабинета;Этаж\n101;1\n'.encode(),'a.csv','rooms'),['101'])

 def test_preview_add_duplicates_revision_and_auth(self):
  data='ФИО\nИванов ИИ\nПетров АБ\nПЕТРОВ АБ\n'.encode('cp1251')
  with patch.object(app,'_save_state') as save, TestClient(app.app) as client:
   headers={'Authorization':'Bearer '+app._create_token()};url='/api/admin/planner/catalog-file/teachers/preview';apply='/api/admin/planner/catalog-file/teachers/apply'
   self.assertEqual(client.post(url,files={'file':('names.csv',data)}).status_code,401)
   r=client.post(url,headers=headers,files={'file':('names.csv',data)});self.assertEqual(r.status_code,200,r.text)
   self.assertEqual(r.json()['added'],['Петров А.Б.']);self.assertEqual(len(r.json()['duplicates']),2);self.assertEqual(save.call_count,0)
   self.assertEqual(client.post(apply,headers=headers,json={'revision':1,'names':['Петров А.Б.']}).status_code,409)
   r=client.post(apply,headers=headers,json={'revision':0,'names':['Петров АБ']});self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['added'],['Петров А.Б.']);self.assertEqual(r.json()['project']['revision'],1);self.assertEqual(save.call_count,1)
   r=client.post('/api/admin/planner/catalog-file/rooms/preview',headers=headers,files={'file':('rooms.csv','Кабинет\n101\n102\n'.encode())});self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['added'],['102'])
   r=client.post('/api/admin/planner/catalog-file/rooms/apply',headers=headers,json={'revision':1,'names':['102']});self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['project']['rooms'][1]['unavailable'],[])
   self.assertEqual(client.post(url,headers=headers,files={'file':('x.pdf',b'x')}).status_code,422)
