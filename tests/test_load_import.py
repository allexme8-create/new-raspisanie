import copy,io,sys,unittest,zipfile,html
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import app,planner,load_import
from fastapi.testclient import TestClient
from openpyxl import Workbook

HEADER=[['№','ФИО, учителя','Основная ступень','','','Старшая ступень'],['','','Предмет','Класс','Кол-во часов','Предмет','Класс','Кол-во часов'],['1','Иванов И.И.','английския язык','5а',3,'английский язык','6а',2],['','','английский язык','5б',3],['','ИТОГО','','',6,'','',2],['','Петров П.П.','английский язык','5а',3]]
def csv_bytes():return ('\n'.join(';'.join(map(str,r+['']*(9-len(r)))) for r in HEADER)).encode('cp1251')
def workbook_bytes():
    book=Workbook();ws=book.active
    for row in HEADER:ws.append(row)
    out=io.BytesIO();book.save(out);return out.getvalue()
class LoadImportTests(unittest.TestCase):
    def test_csv_xlsx_parser_and_fuzzy_confirmation(self):
        for name,buf in [('sample.csv',csv_bytes()),('sample.xlsx',workbook_bytes()),('sample.xls',workbook_bytes())]:
            rows=load_import.parse(buf,name);self.assertEqual(len(rows),4);self.assertEqual(rows[1]['class_name'],'6а');self.assertEqual(rows[2]['teacher'],'Иванов И.И.')
        self.assertEqual(load_import.match('Иванов ИИ',['Иванов И.И.'])['value'],'Иванов И.И.')
        self.assertEqual(load_import.match('английския язык',['Ин.яз.'])['suggestion'],'Ин.яз.')
        self.assertEqual(load_import.match('Иванов',['Иванов И.И.','Иванов А.А.'])['value'],'')
    def test_ods_and_incomplete_row(self):
        content='<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:spreadsheet><table:table>'
        for row in HEADER:
            content+='<table:table-row>'+''.join('<table:table-cell><text:p>'+html.escape(str(v))+'</text:p></table:table-cell>' for v in row)+'</table:table-row>'
        content+='</table:table></office:spreadsheet></office:body></office:document-content>'
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w') as archive:archive.writestr('content.xml',content)
        self.assertEqual(len(load_import.parse(output.getvalue(),'load.ods')),4)
        broken=csv_bytes().replace('английския язык;5а;3'.encode('cp1251'),'английския язык;5а;1,5'.encode('cp1251'))
        with self.assertRaises(load_import.ParseError):load_import.parse(broken,'bad.csv')

    def test_template_partial_files_and_edit_load(self):
        old=copy.deepcopy(app.state)
        try:
            app.state['planner']=planner.Project(classes=[planner.SchoolClass(name=n) for n in ['5а','5б','7а']],teachers=[planner.Teacher(name=n) for n in ['Иванова И.И.','Петров П.П.']],subjects=[planner.Named(name=n) for n in ['Математика','Физика']],rooms=[planner.Room(name='101')]).model_dump()
            app.state['bell_schedule']=None
            with patch.object(app,'_save_state'),TestClient(app.app) as client:
                headers={'Authorization':'Bearer '+app._create_token()}
                sample=client.get('/api/schedule/load-template.csv')
                self.assertEqual(sample.status_code,200);self.assertIn('attachment',sample.headers['content-disposition'])
                self.assertEqual(len(load_import.parse(sample.content,'example.csv')),3)
                lines=sample.content.decode('utf-8-sig').splitlines()
                for rev,line in enumerate((lines[1],lines[3])):
                    part=('\ufeff'+lines[0]+'\r\n'+line+'\r\n').encode('utf-8')
                    preview=client.post('/api/admin/planner/load-import/preview',headers=headers,files={'file':('part.csv',part)})
                    self.assertEqual(preview.status_code,200,preview.text)
                    rows=preview.json()['rows'];self.assertEqual(len(rows),1)
                    apply=client.post('/api/admin/planner/load-import/apply',headers=headers,json={'revision':rev,'rows':[{k:rows[0][k] for k in ('class_name','teacher','subject','per_week')}]})
                    self.assertEqual(apply.status_code,200,apply.text)
                project=apply.json()['project'];self.assertEqual(len(project['loads']),2)
                self.assertEqual({x['subject'] for x in project['loads']},{'Математика','Физика'})
                load=project['loads'][0]
                change={'revision':2,'load_id':load['id'],'class_name':'5б','teacher':'Петров П.П.','subject':'Математика','group':'','room':'101','per_week':5,'max_per_day':2}
                edited=client.post('/api/admin/planner/load-change',headers=headers,json=change)
                self.assertEqual(edited.status_code,200,edited.text)
                edited_load=next(x for x in edited.json()['project']['loads'] if x['id']==load['id'])
                self.assertEqual((edited_load['class_name'],edited_load['teacher'],edited_load['per_week'],edited_load['max_per_day'],edited_load['room']),('5б','Петров П.П.',5,2,'101'))
                self.assertEqual(client.post('/api/admin/planner/load-change',headers=headers,json=change).status_code,409)
                change['revision']=3;change['per_week']=37
                self.assertEqual(client.post('/api/admin/planner/load-change',headers=headers,json=change).status_code,422)
                app.state['planner']['placements']=[{'load_id':load['id'],'day':'Пн','lesson':1,'room':''}]
                before=copy.deepcopy(app.state['planner']);change['per_week']=6
                self.assertEqual(client.post('/api/admin/planner/load-change',headers=headers,json=change).status_code,409)
                self.assertEqual(app.state['planner'],before)
        finally:app.state.clear();app.state.update(old)

    def test_uploaded_load_drives_schedule_generation(self):
        old=copy.deepcopy(app.state)
        try:
            app.state['planner']=planner.Project(classes=[planner.SchoolClass(name='5а')],teachers=[planner.Teacher(name='Иванов И.И.')],subjects=[planner.Named(name='Ин.яз.')],rooms=[planner.Room(name='101')]).model_dump()
            app.state['bell_schedule']={'shifts':{'1':{day:{'1':{'start':'08:00','end':'08:40'},'2':{'start':'09:00','end':'09:40'}} for day in planner.DAYS}}}
            before=copy.deepcopy(app.state['teachers'])
            with patch.object(app,'_save_state'),TestClient(app.app) as client:
                headers={'Authorization':'Bearer '+app._create_token()}
                preview=client.post('/api/admin/planner/load-import/preview',headers=headers,files={'file':('load.csv',csv_bytes())})
                self.assertEqual(preview.status_code,200,preview.text)
                source=preview.json()['rows'][0]
                row={'class_name':source['class_name'],'teacher':source['teacher'],'subject':'Ин.яз.','per_week':source['per_week']}
                applied=client.post('/api/admin/planner/load-import/apply',headers=headers,json={'revision':preview.json()['revision'],'rows':[row]})
                self.assertEqual(applied.status_code,200,applied.text)
                project=applied.json()['project'];self.assertEqual(project['loads'][0]['per_week'],3)
                result=client.post('/api/admin/planner/generate',headers=headers,json={'revision':project['revision']})
                self.assertEqual(result.status_code,200,result.text)
                placements=result.json()['project']['placements']
                self.assertEqual(len(placements),3)
                self.assertTrue(all(p['load_id']==project['loads'][0]['id'] and p['room']=='101' for p in placements))
                self.assertEqual(app.state['teachers'],before)  # Только черновик, без публикации.
        finally:app.state.clear();app.state.update(old)

    def test_preview_auth_import_accumulate_reimport_and_swap(self):
        old=copy.deepcopy(app.state)
        try:
            p=planner.Project(classes=[planner.SchoolClass(name=n) for n in ['5а','5б','6а']],teachers=[planner.Teacher(name=n) for n in ['Иванов И.И.','Петров П.П.']],subjects=[planner.Named(name='Ин.яз.'),planner.Named(name='Математика')],rooms=[planner.Room(name='101')])
            app.state['planner']=p.model_dump();app.state['bell_schedule']=None
            with patch.object(app,'_save_state'),TestClient(app.app) as client:
                url='/api/admin/planner/load-import/preview';h={'Authorization':'Bearer '+app._create_token()}
                self.assertEqual(client.post(url,files={'file':('test.csv',csv_bytes())}).status_code,401)
                response=client.post(url,headers=h,files={'file':('test.csv',csv_bytes())});self.assertEqual(response.status_code,200,response.text)
                data=response.json();self.assertEqual(len(data['rows']),4);self.assertEqual(data['rows'][0]['matches']['subject']['value'],'')
                rows=[{'class_name':r['class_name'],'teacher':r['teacher'],'subject':'Ин.яз.','per_week':r['per_week']} for r in data['rows']]
                a=client.post('/api/admin/planner/load-import/apply',headers=h,json={'revision':0,'rows':rows});self.assertEqual(a.status_code,200,a.text)
                project=a.json()['project'];self.assertEqual(len(project['loads']),4)
                pair=[x for x in project['loads'] if x['class_name']=='5а'];self.assertEqual({x['group'] for x in pair},{'1 группа','2 группа'});self.assertTrue(all(not x['room'] for x in pair))
                self.assertEqual(client.post('/api/admin/planner/load-import/apply',headers=h,json={'revision':0,'rows':rows}).status_code,409)
                a=client.post('/api/admin/planner/load-import/apply',headers=h,json={'revision':1,'rows':rows});self.assertEqual(a.status_code,200);self.assertEqual(a.json()['added'],0)
                extra={'class_name':'5а','teacher':'Иванов И.И.','subject':'Математика','per_week':2}
                a=client.post('/api/admin/planner/load-import/apply',headers=h,json={'revision':2,'rows':[extra]});self.assertEqual(a.status_code,200,a.text);self.assertEqual(len(a.json()['project']['loads']),5)
                target=pair[0];a=client.post('/api/admin/planner/load-change',headers=h,json={'revision':3,'load_id':target['id'],'group':pair[1]['group'],'room':'101'});self.assertEqual(a.status_code,200,a.text)
                changed={x['id']:x for x in a.json()['project']['loads']};self.assertEqual(changed[pair[0]['id']]['group'],pair[1]['group']);self.assertEqual(changed[pair[1]['id']]['group'],pair[0]['group']);self.assertEqual(changed[pair[0]['id']]['room'],'101')
                before=copy.deepcopy(app.state['planner']);duplicate=[rows[0],rows[0]];a=client.post('/api/admin/planner/load-import/apply',headers=h,json={'revision':4,'rows':duplicate});self.assertEqual(a.status_code,422);self.assertEqual(app.state['planner'],before)
        finally:app.state.clear();app.state.update(old)
if __name__=='__main__':unittest.main()
