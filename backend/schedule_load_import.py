"""Сопоставление опубликованной недельной сетки с учебной нагрузкой.

Не восстанавливает расстановку уроков. При нескольких учителях одного
предмета предлагает предполагаемые группы; разные предметы без метаданных
не сопоставляет автоматически.
"""
from collections import Counter
import schedule_map

SERVICE={'классный час','сфу','экскурсия'}


def text(value):
    return ' '.join(str(value or '').split())


def from_schedule(data, normalize_teacher):
    grouped={}
    skipped=[]
    classes=list(dict.fromkeys(c for kind in ('teachers','subjects') for c in (data.get(kind) or {}).get('classes',[])))
    entries={cls:schedule_map.entries(data,cls) for cls in classes}
    cohorts={}
    for cls in classes:
        for entry in entries[cls]:
            t,s=entry['teachers'],entry['subjects']
            teachers=[normalize_teacher(text(x)) for x in t.get('names',[]) if text(x)]
            subjects=[text(x) for x in s.get('names',[]) if text(x)]
            if not (t.get('groups') or s.get('groups')) and len(teachers)>1 and len(set(x.casefold() for x in teachers))==len(teachers) and len(subjects)==1 and subjects[0].casefold() not in SERVICE:
                cohort=cohorts.setdefault((cls.casefold(),subjects[0].casefold()),{})
                for name in teachers:cohort.setdefault(name.casefold(),name)
    proposals={key:{name:f'{index} группа' for index,name in enumerate(sorted(names),1)} for key,names in cohorts.items()}
    for cls in classes:
        for entry in entries[cls]:
            t,s=entry['teachers'],entry['subjects']
            teachers=[text(x) for x in t.get('names',[]) if text(x)]
            subjects=[text(x) for x in s.get('names',[]) if text(x)]
            if not teachers and not subjects:continue
            if all(x.casefold() in SERVICE for x in teachers+subjects):continue
            prefix=f"{cls}, {entry['day']}, урок {entry['lesson']}"
            # The constructor's published grids retain exact group associations.
            tg=t.get('groups') or [];sg=s.get('groups') or []
            if not isinstance(tg,list) or not isinstance(sg,list) or any(not isinstance(g,dict) for g in tg+sg):
                skipped.append(prefix+': некорректные данные групп.');continue
            def group_key(g):
                return (text(g.get('group')).casefold(),normalize_teacher(text(g.get('teacher'))).casefold(),text(g.get('subject')).casefold())
            if tg and sg and Counter(group_key(g) for g in tg)!=Counter(group_key(g) for g in sg):
                skipped.append(prefix+': данные групп в файлах не совпадают.');continue
            records=tg or sg
            inferred=False
            if records:
                if not all(isinstance(g,dict) and text(g.get('teacher')) and text(g.get('subject')) for g in records):
                    skipped.append(prefix+': неполные сведения об учителе или предмете в группах.');continue
                if len({group_key(g) for g in records})!=len(records):
                    skipped.append(prefix+': повторяются данные группы.');continue
                if ({normalize_teacher(x).casefold() for x in teachers}!={group_key(g)[1] for g in records} or
                    {x.casefold() for x in subjects}!={group_key(g)[2] for g in records}):
                    skipped.append(prefix+': данные групп не совпадают с учителями или предметами ячейки.');continue
                rows=[(normalize_teacher(text(g['teacher'])),text(g['subject']),text(g.get('group'))) for g in records]
            elif len(subjects)==1 and len(teachers)>=1 and len(set(x.casefold() for x in teachers))==len(teachers):
                subject=subjects[0];cohort=proposals.get((cls.casefold(),subject.casefold()),{})
                inferred=bool(cohort) and all(normalize_teacher(t).casefold() in cohort for t in teachers)
                if len(teachers)>1 and not inferred:
                    skipped.append(prefix+': невозможно определить предполагаемые группы.');continue
                rows=[(normalize_teacher(t),subject,cohort.get(normalize_teacher(t).casefold(),'') if inferred else '') for t in teachers]
            else:
                skipped.append(prefix+': невозможно надёжно сопоставить учителей и предметы без данных групп.');continue
            if any(not teacher or not subject or len(teacher)>80 or len(subject)>80 or len(group)>80 or len(cls)>80 or teacher.casefold() in SERVICE or subject.casefold() in SERVICE for teacher,subject,group in rows):
                skipped.append(prefix+': служебная или некорректная запись.');continue
            for teacher,subject,group in rows:
                key=(cls.casefold(),teacher.casefold(),subject.casefold(),group.casefold())
                item=grouped.setdefault(key,{'class_name':cls,'teacher':teacher,'subject':subject,'group':group,'per_week':0,'days':Counter(),'inferred':False})
                item['per_week']+=1;item['days'][entry['day']]+=1;item['inferred']|=inferred
    result=[]
    for item in grouped.values():
        if item['per_week']>36 or max(item['days'].values())>12:
            skipped.append(f"{item['class_name']}, {item['subject']}, {item['teacher']}: превышен предел часов конструктора.");continue
        item['max_per_day']=max(item.pop('days').values())
        result.append(item)
    result.sort(key=lambda r:(r['class_name'].casefold(),r['subject'].casefold(),r['teacher'].casefold(),r['group'].casefold()))
    return result,skipped
