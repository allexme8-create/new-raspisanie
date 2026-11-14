"""Неразрушаемая карта импортированного расписания, включая исходные ячейки."""
import copy
import re

DAYS=("Пн","Вт","Ср","Чт","Пт","Сб")


def snapshot(state):
    return {k:copy.deepcopy(state.get(k)) for k in ("teachers","subjects","second_shift_classes","bell_schedule")}


def clock(value):
    match=re.fullmatch(r"(\d{1,2}):(\d{2})",str(value or ""))
    return int(match[1])*60+int(match[2]) if match else None


def period(data,shift,day,number):
    return ((data.get("bell_schedule") or {}).get("shifts",{}).get(str(shift),{}).get(day,{}).get(str(number))) or {}


def offset(data,day):
    first=(data.get("bell_schedule") or {}).get("shifts",{}).get("1",{}).get(day,{})
    start=clock(period(data,2,day,1).get("start"))
    if start is not None:
        for number,p in first.items():
            a,b=clock(p.get("start")),clock(p.get("end"))
            if a is not None and b is not None and a<=start<b:return max(0,int(number)-1)
    return max([int(n) for n in first if str(n).isdigit()] or [0])


def getcell(data,kind,day,raw,cls):
    return ((data.get(kind) or {}).get("grid",{}).get(day,{}).get(str(raw),{}).get(cls))


def global_grid(data,cls):
    teachers=data.get("teachers") or {};subjects=data.get("subjects") or {}
    if cls not in (data.get("second_shift_classes") or []) or teachers.get("numbering")=="local" or subjects.get("numbering")=="local":return False
    if not (data.get("bell_schedule") or {}).get("shifts",{}).get("2"):return False
    higher=lower=False
    for day in DAYS:
        ts=teachers.get("grid",{}).get(day,{});ss=subjects.get("grid",{}).get(day,{})
        for raw in set(ts)|set(ss):
            if not str(raw).isdigit():continue
            t=getcell(data,"teachers",day,raw,cls) or {};s=getcell(data,"subjects",day,raw,cls) or {}
            if not (t.get("names") or t.get("raw") or s.get("names") or s.get("raw")):continue
            n=int(raw);off=offset(data,day)
            higher |= n>off;lower |= n<off-1
    return higher and not lower


def entries(data,cls):
    result=[];is_second=cls in (data.get("second_shift_classes") or []);is_global=global_grid(data,cls)
    for day in DAYS:
        grids=[(data.get(k) or {}).get("grid",{}).get(day,{}) for k in ("teachers","subjects")]
        raws=sorted({str(n) for grid in grids for n in grid if str(n).isdigit()},key=int)
        for raw in raws:
            t=getcell(data,"teachers",day,raw,cls) or {};s=getcell(data,"subjects",day,raw,cls) or {}
            if not (t.get("names") or t.get("raw") or s.get("names") or s.get("raw")):continue
            pre=is_global and int(raw)<=offset(data,day);lesson=int(raw)-offset(data,day) if is_global and not pre else int(raw)
            result.append({"day":day,"raw":raw,"lesson":lesson,"shift":1 if pre or not is_second else 2,"before_shift":pre,"teachers":t,"subjects":s})
    return result


def destination(data,cls,day,lesson):
    return str(lesson+offset(data,day) if global_grid(data,cls) else lesson)


def putcell(data,kind,day,raw,cls,cell):
    grid=data[kind]["grid"];slots=grid.setdefault(day,{}).setdefault(str(raw),{})
    if cell is None:slots.pop(cls,None)
    else:slots[cls]=cell
