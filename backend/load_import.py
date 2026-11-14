"""Разбор учебной нагрузки: одна или несколько троек предмет/класс/часы."""
import re
import io
import zipfile
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from schedule_parser import read_rows, ParseError


def norm(value):
    return re.sub(r'[^а-яa-z0-9]+','',str(value).casefold().replace('ё','е'))


def match(value, choices):
    target=norm(value)
    exact=[name for name in choices if norm(name)==target]
    if len(exact)==1:return {'value':exact[0],'suggestion':'','confidence':'exact'}
    if target in ('английскийязык','английскияязык','английскияязик'):
        aliases=[name for name in choices if norm(name) in ('иняз','иностранныйязык','английский','английскийязык')]
        if len(aliases)==1:return {'value':'','suggestion':aliases[0],'confidence':'review'}
    scored=sorted(((SequenceMatcher(None,target,norm(name)).ratio(),name) for name in choices if norm(name)),reverse=True)
    if scored and scored[0][0]>=.70 and (len(scored)==1 or scored[0][0]-scored[1][0]>=.035):
        return {'value':'','suggestion':scored[0][1],'confidence':'review'}
    return {'value':'','suggestion':'','confidence':'missing'}


def ods_rows(buf):
    try:
        with zipfile.ZipFile(io.BytesIO(buf)) as archive:
            info=archive.getinfo('content.xml')
            if info.file_size>20*1024*1024:raise ParseError('Таблица ODS слишком большая.')
            root=ET.fromstring(archive.read(info))
        ns={'t':'urn:oasis:names:tc:opendocument:xmlns:table:1.0','text':'urn:oasis:names:tc:opendocument:xmlns:text:1.0','o':'urn:oasis:names:tc:opendocument:xmlns:office:1.0'}
        sheet=root.find('.//t:table',ns)
        if sheet is None:raise ParseError('В ODS нет листов.')
        rows=[]
        for row in sheet.findall('.//t:table-row',ns):
            cells=[]
            for cell in row:
                if cell.tag not in ('{'+ns['t']+'}table-cell','{'+ns['t']+'}covered-table-cell'):continue
                repeat=int(cell.get('{'+ns['t']+'}number-columns-repeated','1'))
                value=' '.join(''.join(p.itertext()) for p in cell.findall('.//text:p',ns)).strip() or cell.get('{'+ns['o']+'}value','')
                if len(cells)+repeat>1000:
                    if value:raise ParseError('Слишком много столбцов в ODS.')
                    repeat=max(0,1000-len(cells))
                cells.extend([value]*repeat)
            repeats=int(row.get('{'+ns['t']+'}number-rows-repeated','1'))
            if len(rows)+repeats>5000:
                if any(cells):raise ParseError('Слишком много строк в ODS.')
                repeats=max(0,5000-len(rows))
            rows.extend([cells]*repeats)
        return rows
    except (zipfile.BadZipFile,KeyError,ET.ParseError,ValueError) as exc:
        raise ParseError('Не удалось прочитать таблицу ODS.') from exc


def parse(buf, filename):
    rows=ods_rows(buf) if filename.lower().endswith('.ods') else read_rows(buf,filename)
    headers=[];teacher_col=None;header_index=None
    for i,row in enumerate(rows):
        vals=[norm(c or '') for c in row]
        for j,v in enumerate(vals):
            if 'фио' in v or ('учител' in v and not 'кол' in v):teacher_col=j
        triples=[]
        for j,v in enumerate(vals):
            if 'предмет' in v:
                cls=next((k for k in range(j+1,min(len(vals),j+4)) if 'класс' in vals[k]),None)
                hrs=next((k for k in range((cls+1) if cls is not None else j+1,min(len(vals),j+6)) if 'час' in vals[k] or 'недел' in vals[k]),None)
                if cls is not None and hrs is not None:triples.append((j,cls,hrs))
        if triples:
            headers=triples;header_index=i;break
    if not headers or teacher_col is None:raise ParseError('Не найдены заголовки ФИО учителя, предмет, класс и количество часов. Поддерживается таблица по образцу.')
    result=[];current='';errors=[]
    for i,row in enumerate(rows[header_index+1:],start=header_index+2):
        val=lambda col: str(row[col] if col<len(row) and row[col] is not None else '').strip()
        name=val(teacher_col)
        if name and re.search(r'итого|всего|сумма',name,re.I):current='';continue
        if name:current=name
        for subj,cls,hrs in headers:
            subject,classname,hours=val(subj),val(cls),val(hrs)
            if not subject and not classname and not hours:continue
            if not subject and not classname:continue
            try:
                n=float(hours.replace(',','.')); n=int(n) if n.is_integer() else 0
            except ValueError:n=0
            if not current or not subject or not classname or n<1 or n>36:
                errors.append(f'Строка {i}: заполните учителя, предмет, класс и целое число часов от 1 до 36.');continue
            result.append({'line':i,'teacher':current,'subject':subject,'class_name':classname,'per_week':n})
    if errors:raise ParseError(' '.join(errors[:8]))
    if not result:raise ParseError('В файле не найдено строк нагрузки.')
    if len(result)>5000:raise ParseError('В одном файле допускается не более 5000 строк.')
    return result
