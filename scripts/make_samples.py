#!/usr/bin/env python3
"""Генерирует два тестовых файла расписания (учителя + предметы) в samples/."""
import random
from pathlib import Path

from openpyxl import Workbook

DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб"]
CLASSES = ["5а", "5б", "6а", "6б", "7а", "7б", "8а", "9а", "10а", "11а", "11б"]
SUBJECTS = [
    ("Математика", 5), ("Русский язык", 4), ("Литература", 3), ("Англ.яз", 3),
    ("История", 2), ("Физика", 2), ("Информатика", 1), ("Биология", 2),
    ("География", 1), ("Физ-ра", 2), ("Изо", 1), ("Технология", 1),
]
TEACHERS = ["Иванова ИИ", "Петрова АС", "Сидоров ПН", "Кузнецова ОВ", "Морозова ТА",
            "Васильев ДС", "Смирнова ЕП", "Новикова ЛГ", "Фёдоров АВ", "Орлова НИ",
            "Белов СМ", "Громова ЮВ"]
ROOMS = [str(r) for r in [12, 14, 15, 21, 22, 23, 31, 32, 33, 41, 305, 307]]

random.seed(42)


def make(kind: str, path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.append(["", "Урок"] + CLASSES)
    for day in DAYS:
        lessons = random.randint(5, 7)
        for lesson in range(1, lessons + 1):
            row = [day if lesson == 1 else "", lesson]
            for _cls in CLASSES:
                if random.random() < 0.08:
                    row.append("")
                    continue
                if random.random() < 0.04:
                    row.append("Классный час")
                    continue
                subj, _ = random.choice(SUBJECTS)
                room = random.choice(ROOMS)
                if kind == "teachers":
                    row.append(f"{random.choice(TEACHERS)} ({room})")
                else:
                    row.append(f"{subj} ({room})")
            ws.append(row)
    ws.insert_rows(0)  # пустая первая строка — как в реальных выгрузках
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    print(f"Создан {path}")


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    make("teachers", root / "samples" / "Пример_учителя.xlsx")
    make("subjects", root / "samples" / "Пример_предметы.xlsx")
