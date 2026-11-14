"""Первый этап конструктора: черновик, проверка ограничений и подбор уроков."""
from __future__ import annotations

from collections import Counter
import re
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator

DAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб")


class Named(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Название не может быть пустым")
        return value


class SchoolClass(Named):
    shift: int = Field(default=1, ge=1, le=2)
    max_daily: int = Field(default=7, ge=1, le=12)


class ClassGroup(Named):
    class_name: str = Field(min_length=1, max_length=80)
    inferred: bool = False


class Slot(BaseModel):
    day: str
    shift: int = Field(ge=1, le=2)
    lesson: int = Field(ge=1, le=12)

    @field_validator("day")
    @classmethod
    def valid_day(cls, value: str) -> str:
        if value not in DAYS:
            raise ValueError("Неизвестный день")
        return value


class Room(Named):
    unavailable: list[Slot] = Field(default_factory=list, max_length=144)

    @field_validator("unavailable")
    @classmethod
    def unique_unavailable(cls, slots: list[Slot]) -> list[Slot]:
        keys = [(slot.day, slot.shift, slot.lesson) for slot in slots]
        if len(keys) != len(set(keys)):
            raise ValueError("Ограничение кабинета повторяется")
        return slots


class Teacher(Named):
    preferred_room: str = Field(default="", max_length=80)
    unavailable: list[Slot] = Field(default_factory=list, max_length=144)


class Load(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    class_name: str
    teacher: str
    subject: str
    room: str
    per_week: int = Field(ge=1, le=36)
    max_per_day: int = Field(default=1, ge=1, le=12)
    group: str = Field(default="", max_length=80)

    @field_validator("group")
    @classmethod
    def clean_group(cls, value: str) -> str:
        return " ".join(value.split())


class Placement(BaseModel):
    load_id: str
    day: str
    lesson: int = Field(ge=1, le=12)
    room: str = Field(default="", max_length=80)

    @field_validator("day")
    @classmethod
    def valid_day(cls, value: str) -> str:
        if value not in DAYS:
            raise ValueError("Неизвестный день")
        return value


class Preference(BaseModel):
    scope: Literal["class", "grade"]
    scope_value: str = Field(min_length=1, max_length=80)
    subject: str = Field(min_length=1, max_length=80)
    kind: Literal["avoid_lesson", "avoid_before"]
    lesson: int | None = Field(default=None, ge=1, le=12)
    next_subject: str = Field(default="", max_length=80)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_rule(self):
        if self.scope == "grade" and not re.fullmatch(r"(?:[1-9]|1[01])", self.scope_value):
            raise ValueError("Параллель должна быть от 1 до 11")
        if self.kind == "avoid_lesson" and self.lesson is None:
            raise ValueError("Укажите номер урока")
        if self.kind == "avoid_before" and not self.next_subject:
            raise ValueError("Укажите следующий предмет")
        return self


class Project(BaseModel):
    revision: int = Field(default=0, ge=0)
    classes: list[SchoolClass] = Field(default_factory=list, max_length=500)
    teachers: list[Teacher] = Field(default_factory=list, max_length=200)
    groups: list[ClassGroup] = Field(default_factory=list, max_length=2000)
    subjects: list[Named] = Field(default_factory=list, max_length=200)
    rooms: list[Room] = Field(default_factory=list, max_length=200)
    loads: list[Load] = Field(default_factory=list, max_length=10000)
    placements: list[Placement] = Field(default_factory=list, max_length=30000)
    preferences: list[Preference] = Field(default_factory=list, max_length=1000)


def references(project: Project) -> list[str]:
    errors = []
    for label, items in (("класса", project.classes), ("учителя", project.teachers),
                         ("предмета", project.subjects), ("кабинета", project.rooms)):
        names = [x.name.casefold() for x in items]
        if len(names) != len(set(names)):
            errors.append(f"Повторяется название {label}.")
    group_keys = [(g.class_name.casefold(), g.name.casefold()) for g in project.groups]
    if len(group_keys) != len(set(group_keys)):
        errors.append("Повторяется название группы в одном классе.")
    class_names = {c.name for c in project.classes}
    for group in project.groups:
        if group.class_name not in class_names:
            errors.append(f"Группа {group.name}: неизвестный класс «{group.class_name}».")
    subjects_set={x.name for x in project.subjects}
    for rule in project.preferences:
        if rule.scope == "class" and rule.scope_value not in class_names:
            errors.append(f"Предпочтение: неизвестный класс «{rule.scope_value}».")
        if rule.subject not in subjects_set or (rule.kind == "avoid_before" and rule.next_subject not in subjects_set):
            errors.append("Предпочтение ссылается на отсутствующий предмет.")
    ids = [x.id for x in project.loads]
    if len(ids) != len(set(ids)):
        errors.append("Повторяется идентификатор нагрузки.")
    for load in project.loads:
        for label, name, items in (("класс", load.class_name, project.classes),
                                   ("учитель", load.teacher, project.teachers),
                                   ("предмет", load.subject, project.subjects),
                                   ("кабинет", load.room, project.rooms)):
            if label == "кабинет" and not name:
                continue
            if name not in {x.name for x in items}:
                errors.append(f"Нагрузка {load.id}: неизвестный {label} «{name}».")
    room_names={r.name for r in project.rooms}
    for teacher in project.teachers:
        if teacher.preferred_room and teacher.preferred_room not in room_names:
            errors.append(f"Учитель {teacher.name}: приоритетный кабинет отсутствует в справочнике.")
    for placement in project.placements:
        if placement.room and placement.room not in room_names:
            errors.append(f"Урок {placement.load_id}: кабинет отсутствует в справочнике.")
    loads_by_id={load.id:load for load in project.loads}
    for placement in project.placements:
        load=loads_by_id.get(placement.load_id)
        if load and load.room and placement.room and placement.room!=load.room:
            errors.append(f"Урок {placement.load_id}: кабинет противоречит закреплённому в нагрузке.")
    if any(p.load_id not in ids for p in project.placements):
        errors.append("Есть уроки с неизвестной нагрузкой.")
    return errors


def period(bells: dict | None, day: str, shift: int, lesson: int) -> tuple[int, int] | None:
    p = (bells or {}).get("shifts", {}).get(str(shift), {}).get(day, {}).get(str(lesson))
    try:
        start, end = p["start"], p["end"]
        a, b = (int(start[:2]) * 60 + int(start[3:]), int(end[:2]) * 60 + int(end[3:]))
        return (a, b) if a < b else None
    except (TypeError, KeyError, ValueError):
        return None


def issues(project: Project, bells: dict | None, complete: bool = False) -> list[str]:
    errors = references(project)
    if errors:
        return errors
    loads = {x.id: x for x in project.loads}
    classes = {x.name: x for x in project.classes}
    teachers = {x.name: x for x in project.teachers}
    rooms = {x.name: x for x in project.rooms}
    counts: Counter = Counter()
    days: dict[tuple[str, str], set[int]] = {}
    subjects: Counter = Counter()
    scheduled = []
    for p in project.placements:
        load = loads[p.load_id]
        cls = classes[load.class_name]
        label = f"{p.day}, урок {p.lesson}, {load.class_name}"
        room = load.room or p.room
        if not room:
            errors.append(f"{label}: не указан кабинет.")
        counts[load.id] += 1
        days.setdefault((load.class_name, p.day), set()).add(p.lesson)
        subjects[(load.id, p.day)] += 1
        time = period(bells, p.day, cls.shift, p.lesson)
        if not time:
            errors.append(f"{label}: нет времени звонков для {cls.shift}-й смены.")
            continue
        teacher = teachers[load.teacher]
        for slot in teacher.unavailable:
            unavailable_time = period(bells, slot.day, slot.shift, slot.lesson)
            if slot.day == p.day and unavailable_time and time[0] < unavailable_time[1] and unavailable_time[0] < time[1]:
                errors.append(f"{label}: учитель {load.teacher} недоступен.")
                break
        if room:
            for slot in rooms[room].unavailable:
                unavailable_time = period(bells, slot.day, slot.shift, slot.lesson)
                if slot.day == p.day and unavailable_time and time[0] < unavailable_time[1] and unavailable_time[0] < time[1]:
                    errors.append(f"{label}: кабинет {room} недоступен.")
                    break
        for other, other_load, other_time in scheduled:
            if p.day == other.day and time[0] < other_time[1] and other_time[0] < time[1]:
                shared = []
                if load.class_name == other_load.class_name and (not load.group or not other_load.group or load.group.casefold() == other_load.group.casefold() or p.lesson != other.lesson): shared.append("класс или группа")
                if load.teacher == other_load.teacher: shared.append("учитель")
                if room and room == (other_load.room or other.room): shared.append("кабинет")
                if shared:
                    errors.append(f"{label}: конфликт ({', '.join(shared)}) с {other_load.class_name}, урок {other.lesson}.")
        scheduled.append((p, load, time))
    for (name, day), lessons in days.items():
        if len(lessons) > classes[name].max_daily:
            errors.append(f"{day}, {name}: превышен дневной предел уроков.")
    for (load_id, day), count in subjects.items():
        if count > loads[load_id].max_per_day:
            errors.append(f"{day}, {loads[load_id].class_name}: превышен дневной предел нагрузки «{loads[load_id].subject}».")
    for load in project.loads:
        if counts[load.id] > load.per_week:
            errors.append(f"{load.class_name}, {load.subject}: уроков больше недельной нагрузки.")
        elif complete and counts[load.id] != load.per_week:
            errors.append(f"{load.class_name}, {load.subject}: расставлено {counts[load.id]} из {load.per_week}.")
    # Недоступность без звонка не должна незаметно игнорироваться.
    for teacher in project.teachers:
        for slot in teacher.unavailable:
            if not period(bells, slot.day, slot.shift, slot.lesson):
                errors.append(f"{teacher.name}: нет звонков для недоступного времени {slot.day}, смена {slot.shift}, урок {slot.lesson}.")
    for room in project.rooms:
        for slot in room.unavailable:
            if not period(bells, slot.day, slot.shift, slot.lesson):
                errors.append(f"Кабинет {room.name}: нет звонков для недоступного времени {slot.day}, смена {slot.shift}, урок {slot.lesson}.")
    return errors


def preference_hits(project: Project, load: Load, day: str, lesson: int, previous: list[tuple[Load, str, int]]) -> list[str]:
    hits=[]
    for rule in project.preferences:
        if not rule.enabled:
            continue
        if rule.scope == "class" and rule.scope_value != load.class_name:
            continue
        if rule.scope == "grade" and not re.match(r"^" + re.escape(rule.scope_value) + r"(?!\d)", load.class_name.strip()):
            continue
        if rule.kind == "avoid_lesson" and load.subject == rule.subject and lesson == rule.lesson:
            hits.append(f"{day}, {load.class_name}: {load.subject} на уроке {lesson}.")
        elif rule.kind == "avoid_before":
            for other, other_day, other_lesson in previous:
                if other_day != day or other.class_name != load.class_name:
                    continue
                if ((load.subject == rule.subject and other.subject == rule.next_subject and other_lesson == lesson + 1) or
                    (other.subject == rule.subject and load.subject == rule.next_subject and lesson == other_lesson + 1)):
                    hits.append(f"{day}, {load.class_name}: {rule.subject} непосредственно перед «{rule.next_subject}».")
    return hits


def preference_warnings(project: Project) -> list[str]:
    loads={load.id: load for load in project.loads}
    previous=[];warnings=[]
    for placement in project.placements:
        load=loads.get(placement.load_id)
        if load:
            warnings.extend(preference_hits(project,load,placement.day,placement.lesson,previous))
            previous.append((load,placement.day,placement.lesson))
    return warnings


def bell_intervals(bells: dict | None) -> dict[str, list[tuple[int, int]]]:
    # Одинаковые звонки смен считаем один раз; пересекающиеся интервалы
    # внутри окна объединяются при подсчёте, чтобы не удваивать окно.
    return {day: sorted({time for shift in (1, 2) for lesson in range(1, 13)
                        if (time := period(bells, day, shift, lesson))}) for day in DAYS}


def gaps_in_day(lessons: list[tuple[int, int]], bell_times: list[tuple[int, int]]) -> int:
    total=0
    intervals=sorted(set(lessons))
    for (_, end), (start, _) in zip(intervals, intervals[1:]):
        between=[(a,b) for a,b in bell_times if a >= end and b <= start]
        previous_end=None
        for a,b in between:
            if previous_end is None or a >= previous_end:
                total+=1
                previous_end=b
            else:
                previous_end=max(previous_end,b)
    return total


def teacher_gap_summary(project: Project, bells: dict | None) -> dict:
    loads={load.id:load for load in project.loads}
    classes={c.name:c for c in project.classes}
    grouped={}
    for placement in project.placements:
        load=loads.get(placement.load_id)
        if not load or load.class_name not in classes:continue
        time=period(bells,placement.day,classes[load.class_name].shift,placement.lesson)
        if time:grouped.setdefault((load.teacher,placement.day),[]).append(time)
    periods=bell_intervals(bells)
    details=[{"teacher":teacher,"day":day,"gaps":count} for (teacher,day),times in sorted(grouped.items())
             if (count:=gaps_in_day(times,periods[day]))]
    return {"total":sum(item["gaps"] for item in details),"details":details}


def generate(project: Project, bells: dict | None, node_limit: int = 30000) -> tuple[Project | None, str]:
    errors = issues(project, bells)
    if errors:
        return None, errors[0]
    if not project.loads:
        return None, "Добавьте учебную нагрузку."
    if not project.rooms:
        return None, "Добавьте кабинеты в справочник."
    if sum(load.per_week for load in project.loads) > 150:
        return None, "Автоподбор первого этапа ограничен 150 уроками; остальные можно расставить вручную."
    work = project.model_copy(deep=True)
    classes = {c.name: c for c in work.classes}
    loads = {x.id: x for x in work.loads}
    teachers = {x.name: x for x in work.teachers}
    counts = Counter(p.load_id for p in work.placements)
    remaining = [load for load in work.loads for _ in range(load.per_week - counts[load.id])]
    slots = {shift: [(day, lesson, period(bells, day, shift, lesson))
                     for day in DAYS for lesson in range(1, 13)
                     if period(bells, day, shift, lesson)] for shift in (1, 2)}
    blocked = {t.name: [(s.day, period(bells, s.day, s.shift, s.lesson)) for s in t.unavailable]
               for t in work.teachers}
    blocked_rooms = {r.name: [(s.day, period(bells, s.day, s.shift, s.lesson)) for s in r.unavailable]
                     for r in work.rooms}
    occupied = {day: [] for day in DAYS}
    daily_class, daily_load = Counter(), Counter()
    for p in work.placements:
        load = loads[p.load_id]
        occupied[p.day].append((load, period(bells, p.day, classes[load.class_name].shift, p.lesson), p.lesson, load.room or p.room))
        daily_class[(load.class_name, p.day, p.lesson)] += 1
        daily_load[(load.id, p.day)] += 1
    remaining.sort(key=lambda load: len(slots[classes[load.class_name].shift]))
    bell_times = bell_intervals(bells)
    teacher_days = {}
    for day, entries in occupied.items():
        for load, time, _, _ in entries:
            teacher_days.setdefault((load.teacher,day),[]).append(time)
    initial_gaps=sum(gaps_in_day(times,bell_times[day]) for (_,day),times in teacher_days.items())
    nodes = 0
    best = None
    best_score = (float("inf"), float("inf"))
    def search(index: int, cost: int, gaps: int) -> bool:
        nonlocal nodes, best, best_score
        if index == len(remaining):
            score=(gaps,cost)
            if score < best_score:
                best = work.model_copy(deep=True)
                best_score = score
            return score == (0,0)
        if nodes >= node_limit or (best_score[0] == 0 and cost >= best_score[1]):
            return False
        load = remaining[index]
        cls = classes[load.class_name]
        preferred=teachers[load.teacher].preferred_room
        room_choices=[load.room] if load.room else ([preferred] if preferred else [])+[r.name for r in work.rooms if r.name!=preferred]
        candidates=[]
        for day, lesson, time in slots[cls.shift]:
            previous=[(other,day,other_lesson) for other, _, other_lesson, _ in occupied[day]]
            penalty=len(preference_hits(work,load,day,lesson,previous))
            current=teacher_days.get((load.teacher,day),[])
            gap_delta=gaps_in_day(current+[time],bell_times[day])-gaps_in_day(current,bell_times[day])
            for room in room_choices:
                room_penalty=int(bool(preferred and not load.room and room!=preferred))
                candidates.append((gap_delta,penalty+room_penalty,daily_load[(load.id,day)],lesson,DAYS.index(day),room_choices.index(room),day,time,room))
        candidates.sort()
        for gap_delta, penalty, _, lesson, _, _, day, time, room in candidates:
            nodes += 1
            if nodes > node_limit: return False
            if best_score[0] == 0 and cost + penalty >= best_score[1]: continue
            if (not daily_class[(load.class_name, day, lesson)] and sum(1 for (name, d, _), count in daily_class.items() if name == load.class_name and d == day and count > 0) >= cls.max_daily) or daily_load[(load.id, day)] >= load.max_per_day:
                continue
            if any(d == day and time[0] < t[1] and t[0] < time[1] for d, t in blocked[load.teacher]):
                continue
            if any(d == day and time[0] < t[1] and t[0] < time[1] for d, t in blocked_rooms[room]):
                continue
            if any(time[0] < t[1] and t[0] < time[1] and
                   ((load.class_name == other.class_name and (not load.group or not other.group or load.group.casefold()==other.group.casefold() or time != t or lesson != other_lesson)) or load.teacher == other.teacher or room == other_room)
                   for other, t, other_lesson, other_room in occupied[day]):
                continue
            work.placements.append(Placement(load_id=load.id, day=day, lesson=lesson, room="" if load.room else room))
            occupied[day].append((load, time, lesson, room))
            teacher_days.setdefault((load.teacher,day),[]).append(time)
            daily_class[(load.class_name, day, lesson)] += 1
            daily_load[(load.id, day)] += 1
            done=search(index + 1,cost+penalty,gaps+gap_delta)
            teacher_days[(load.teacher,day)].pop()
            daily_class[(load.class_name, day, lesson)] -= 1
            daily_load[(load.id, day)] -= 1
            occupied[day].pop()
            work.placements.pop()
            if done: return True
        return False
    search(0,0,initial_gaps)
    if best is not None: return best, ""
    return None, "Не удалось расставить все уроки в пределах ограничений и лимита поиска. Проверьте звонки, доступность и нагрузку. Черновик не изменён."


def public_grids(project: Project) -> tuple[dict, dict]:
    classes = [c.name for c in project.classes]
    loads = {load.id: load for load in project.loads}
    teachers, subjects = {"classes": classes, "grid": {}, "numbering": "local"}, {"classes": classes, "grid": {}, "numbering": "local"}
    for placement in project.placements:
        load = loads[placement.load_id]
        room=load.room or placement.room
        record={"group":load.group,"teacher":load.teacher,"subject":load.subject,"room":room}
        for grid, name in ((teachers, load.teacher), (subjects, load.subject)):
            cells=grid["grid"].setdefault(placement.day, {}).setdefault(str(placement.lesson), {})
            cell=cells.setdefault(load.class_name, {"raw":"", "names":[], "rooms":[], "groups":[]})
            cell["names"].append(name)
            cell["rooms"].append(room)
            cell["groups"].append(record.copy())
            cell["raw"] = ", ".join(cell["names"])
    return teachers, subjects
