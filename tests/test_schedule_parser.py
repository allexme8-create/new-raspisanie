from __future__ import annotations

import sys
import unittest
from datetime import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from schedule_parser import ParseError, parse_bell_schedule, parse_bell_schedule_file, parse_cell  # noqa: E402


BELL_CSV = '''1 смена;;;;2 смена;;;
День недели;Урок;Начало;Окончание;День недели;Урок;Начало;Окончание
Понедельник;"Классный
час";8.00;8.20;Понедельник;"Классный
час";13.15;13.35
;1;8.25;9.05;;1;13.45;14.25
;2;9.15;9.55;;2;14.35;15.15
Вторник;1;8:00;8:40;Вторник;1;13:30;14:10
'''


class ScheduleParserTests(unittest.TestCase):
    def test_parses_attached_bell_table(self) -> None:
        fixture = Path(__file__).resolve().parent / "fixtures" / "Расписание_звонков.csv"
        result = parse_bell_schedule_file(fixture.read_bytes(), fixture.name)
        periods = [
            period
            for days in result["shifts"].values()
            for lessons in days.values()
            for period in lessons.values()
        ]
        self.assertEqual(len(periods), 71)
        self.assertEqual(result["shifts"]["1"]["Пн"]["1"]["start"], "08:25")
        self.assertEqual(result["shifts"]["2"]["Пн"]["1"]["start"], "13:45")
        self.assertNotIn("Сб", result["shifts"]["2"])

    def test_parses_cp1251_csv_with_two_shifts_and_continued_days(self) -> None:
        result = parse_bell_schedule_file(BELL_CSV.encode("cp1251"), "bells.csv")

        self.assertEqual(
            result["shifts"]["1"]["Пн"]["1"],
            {"start": "08:25", "end": "09:05"},
        )
        self.assertEqual(
            result["shifts"]["2"]["Пн"]["2"],
            {"start": "14:35", "end": "15:15"},
        )
        self.assertEqual(result["shifts"]["1"]["Вт"]["1"]["start"], "08:00")
        self.assertNotIn("0", result["shifts"]["1"]["Пн"])

    def test_excel_time_cells_are_normalized(self) -> None:
        rows = [
            ["День недели", "Урок", "Начало", "Окончание"],
            ["Среда", 1, time(9, 5), 0.5],
        ]
        result = parse_bell_schedule(rows)
        self.assertEqual(
            result["shifts"]["1"]["Ср"]["1"],
            {"start": "09:05", "end": "12:00"},
        )

    def test_repeated_room_numbers_are_deduplicated(self) -> None:
        cell = parse_cell("Алгебра, Геометрия ( 302, 302, 301, 302 )")
        self.assertEqual(cell["rooms"], ["302", "301"])

    def test_invalid_interval_is_rejected(self) -> None:
        with self.assertRaises(ParseError):
            parse_bell_schedule([["Понедельник", 1, "09:00", "08:50"]])

    def test_non_bell_file_extension_is_rejected(self) -> None:
        with self.assertRaises(ParseError):
            parse_bell_schedule_file(BELL_CSV.encode("utf-8"), "bells.txt")


if __name__ == "__main__":
    unittest.main()
