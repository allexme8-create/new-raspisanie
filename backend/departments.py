"""Departments and safe extraction of teacher names from workload tables."""
import re
from typing import Annotated
from pydantic import Field
import load_import
from schedule_parser import read_rows, ParseError

Department = Annotated[str, Field(min_length=1, max_length=80)]
NAMES = ('Филология', 'Информатика и технология', 'Естественные науки', 'Математика', 'Физическая культура', 'Иностранные языки', 'Вакансия')


def read_teachers(buf, filename):
    rows = load_import.ods_rows(buf) if filename.lower().endswith('.ods') else read_rows(buf, filename)
    if len(rows) > 5000:
        raise ParseError('В файле допускается не более 5000 строк.')
    col = None; header = None
    for i, row in enumerate(rows[:20]):
        for j, value in enumerate(row):
            key = re.sub(r'[^а-яёa-z]+', '', str(value or '').lower())
            if key in ('фиоучителя', 'фиоучителей', 'фиопедагога', 'фио', 'учитель'):
                col = j; header = i; break
        if col is not None: break
    if col is None:
        raise ParseError('Не найден столбец ФИО учителя.')
    names=[]; skipped=[]; seen=set()
    for row in rows[header+1:]:
        raw=' '.join(str(row[col] or '').split()) if col<len(row) else ''
        if not raw or re.fullmatch(r'(итого|всего|сумма).*', raw, re.I):continue
        if not re.fullmatch(r'[А-ЯЁа-яёA-Za-z-]+\s+[А-ЯЁA-Zа-яёa-z.\s-]+',raw) or len(raw)>80:
            if raw not in skipped:skipped.append(raw[:80])
            continue
        key=re.sub(r'[.\s]+','',raw).casefold()
        if key not in seen:seen.add(key);names.append(raw)
    if not names: raise ParseError('В столбце ФИО не найдены имена учителей.')
    return names, skipped
