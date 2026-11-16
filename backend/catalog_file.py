"""Чтение таблиц справочников учителей и кабинетов без изменения базы."""
import re
from load_import import ods_rows
from schedule_parser import read_rows, ParseError


def text(value):
    if value is None:return ''
    if isinstance(value,float) and value.is_integer():value=int(value)
    return ' '.join(str(value).split())


def parse(buf, filename, kind):
    rows=ods_rows(buf) if filename.lower().endswith('.ods') else read_rows(buf,filename)
    if len(rows)>5000:raise ParseError('В файле допускается не более 5000 строк.')
    header=None;cols=None
    for index,row in enumerate(rows[:20]):
        labels=[re.sub(r'[^а-яёa-z0-9]+','',text(x).lower()) for x in row]
        if kind=='teachers':
            whole=next((i for i,x in enumerate(labels) if x in ('фио','фиоучителя','фиопедагога','фиоучителей','учитель','педагог','сотрудник','фамилияимяотчество')),None)
            surname=next((i for i,x in enumerate(labels) if x in ('фамилия','фамилияучителя')),None)
            first=next((i for i,x in enumerate(labels) if x=='имя'),None)
            middle=next((i for i,x in enumerate(labels) if x=='отчество'),None)
            if whole is not None:header=index;cols=[whole];break
            if surname is not None and first is not None:header=index;cols=[i for i in (surname,first,middle) if i is not None];break
        else:
            col=next((i for i,x in enumerate(labels) if x in ('кабинет','номеркабинета','кабинета','кабинеты','названиекабинета','учебныйкабинет','аудитория','помещение')),None)
            if col is None:col=next((i for i,x in enumerate(labels) if x in ('номер','название')),None)
            if col is not None:header=index;cols=[col];break
    if cols is None:
        nonempty=[row for row in rows if any(text(x) for x in row)]
        if not nonempty:raise ParseError('Таблица пуста.')
        if any(sum(bool(text(x)) for x in row)>1 for row in nonempty):
            raise ParseError('Не найдены заголовки. Укажите столбец «ФИО» или «Кабинет», либо используйте таблицу из одного столбца.')
        cols=[next(i for i,x in enumerate(nonempty[0]) if text(x))];header=-1
        if any(any(text(x) for i,x in enumerate(row) if i!=cols[0]) for row in nonempty):
            raise ParseError('Данные без заголовка должны находиться в одном и том же столбце.')
    result=[]
    for index,row in enumerate(rows[header+1:],start=header+2):
        values=[text(row[col]) if col<len(row) else '' for col in cols]
        if not any(values):continue
        if len(cols)>1 and not all(values[:2]):raise ParseError(f'Строка {index}: укажите фамилию и имя.')
        name=' '.join(x for x in values if x)
        if len(name)>80:raise ParseError(f'Строка {index}: значение длиннее 80 символов.')
        result.append(name)
    if not result:raise ParseError('В таблице не найдено данных.')
    return result
