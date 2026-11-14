"""Первый этап конструктора: черновик, проверка ограничений и подбор уроков."""
from __future__ import annotations

from collections import Counter
from pydantic import BaseModel, Field, field_validator

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


class Teacher(Named):
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

    @field_validator("day")
    @classmethod
    def valid_day(cls, value: str) -> str:
        if value not in DAYS:
            raise ValueError("Неизвестный день")
        return value


class Project(BaseModel):
    revision: int = Field(default=0, ge=0)
    classes: list[SchoolClass] = Field(default_factory=list, max_length=500)
    teachers: list[Teacher] = Field(default_factory=list, max_length=200)
    groups: list[ClassGroup] = Field(default_factory=list, max_length=2000)
    subjects: list[Named] = Field(default_factory=list, max_length=200)
    rooms: list[Named] = Field(default_factory=list, max_length=200)
    loads: list[Load] = Field(default_factory=list, max_length=10000)
    placements: list[Placement] = Field(default_factory=list, max_length=30000)


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
    missing_rooms = [x for x in project.loads if not x.room]
    if missing_rooms:
        errors.append(f"Укажите кабинет для {len(missing_rooms)} записей нагрузки перед расстановкой и публикацией.")
    loads = {x.id: x for x in project.loads}
    classes = {x.name: x for x in project.classes}
    teachers = {x.name: x for x in project.teachers}
    counts: Counter = Counter()
    days: dict[tuple[str, str], set[int]] = {}
    subjects: Counter = Counter()
    scheduled = []
    for p in project.placements:
        load = loads[p.load_id]
        cls = classes[load.class_name]
        label = f"{p.day}, урок {p.lesson}, {load.class_name}"
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
        for other, other_load, other_time in scheduled:
            if p.day == other.day and time[0] < other_time[1] and other_time[0] < time[1]:
                shared = []
                if load.class_name == other_load.class_name and (not load.group or not other_load.group or load.group.casefold() == other_load.group.casefold() or p.lesson != other.lesson): shared.append("класс или группа")
                if load.teacher == other_load.teacher: shared.append("учитель")
                if load.room == other_load.room: shared.append("кабинет")
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
    return errors


def generate(project: Project, bells: dict | None, node_limit: int = 30000) -> tuple[Project | None, str]:
    errors = issues(project, bells)
    if errors:
        return None, errors[0]
    if not project.loads:
        return None, "Добавьте учебную нагрузку."
    if sum(load.per_week for load in project.loads) > 150:
        return None, "Автоподбор первого этапа ограничен 150 уроками; остальные можно расставить вручную."
    work = project.model_copy(deep=True)
    classes = {c.name: c for c in work.classes}
    loads = {x.id: x for x in work.loads}
    counts = Counter(p.load_id for p in work.placements)
    remaining = [load for load in work.loads for _ in range(load.per_week - counts[load.id])]
    slots = {shift: [(day, lesson, period(bells, day, shift, lesson))
                     for day in DAYS for lesson in range(1, 13)
                     if period(bells, day, shift, lesson)] for shift in (1, 2)}
    blocked = {t.name: [(s.day, period(bells, s.day, s.shift, s.lesson)) for s in t.unavailable]
               for t in work.teachers}
    occupied = {day: [] for day in DAYS}
    daily_class, daily_load = Counter(), Counter()
    for p in work.placements:
        load = loads[p.load_id]
        occupied[p.day].append((load, period(bells, p.day, classes[load.class_name].shift, p.lesson), p.lesson))
        daily_class[(load.class_name, p.day, p.lesson)] += 1
        daily_load[(load.id, p.day)] += 1
    remaining.sort(key=lambda load: len(slots[classes[load.class_name].shift]))
    nodes = 0
    def search(index: int) -> bool:
        nonlocal nodes
        if index == len(remaining): return True
        load = remaining[index]
        cls = classes[load.class_name]
        choices = sorted(slots[cls.shift], key=lambda slot: (daily_load[(load.id, slot[0])], slot[1], DAYS.index(slot[0])))
        for day, lesson, time in choices:
            nodes += 1
            if nodes > node_limit: return False
            if (not daily_class[(load.class_name, day, lesson)] and sum(1 for (name, d, _), count in daily_class.items() if name == load.class_name and d == day and count > 0) >= cls.max_daily) or daily_load[(load.id, day)] >= load.max_per_day:
                continue
            if any(d == day and time[0] < t[1] and t[0] < time[1] for d, t in blocked[load.teacher]):
                continue
            if any(time[0] < t[1] and t[0] < time[1] and
                   ((load.class_name == other.class_name and (not load.group or not other.group or load.group.casefold()==other.group.casefold() or time != t or lesson != other_lesson)) or load.teacher == other.teacher or load.room == other.room)
                   for other, t, other_lesson in occupied[day]):
                continue
            work.placements.append(Placement(load_id=load.id, day=day, lesson=lesson))
            occupied[day].append((load, time, lesson))
            daily_class[(load.class_name, day, lesson)] += 1
            daily_load[(load.id, day)] += 1
            if search(index + 1): return True
            daily_class[(load.class_name, day, lesson)] -= 1
            daily_load[(load.id, day)] -= 1
            occupied[day].pop()
            work.placements.pop()
        return False
    if search(0): return work, ""
    return None, "Не удалось расставить все уроки в пределах ограничений и лимита поиска. Проверьте звонки, доступность и нагрузку. Черновик не изменён."


def public_grids(project: Project) -> tuple[dict, dict]:
    classes = [c.name for c in project.classes]
    loads = {load.id: load for load in project.loads}
    teachers, subjects = {"classes": classes, "grid": {}, "numbering": "local"}, {"classes": classes, "grid": {}, "numbering": "local"}
    for placement in project.placements:
        load = loads[placement.load_id]
        record={"group":load.group,"teacher":load.teacher,"subject":load.subject,"room":load.room}
        for grid, name in ((teachers, load.teacher), (subjects, load.subject)):
            cells=grid["grid"].setdefault(placement.day, {}).setdefault(str(placement.lesson), {})
            cell=cells.setdefault(load.class_name, {"raw":"", "names":[], "rooms":[], "groups":[]})
            cell["names"].append(name)
            cell["rooms"].append(load.room)
            cell["groups"].append(record.copy())
            cell["raw"] = ", ".join(cell["names"])
    return teachers, subjects
