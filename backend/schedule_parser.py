"""
Парсер файлов расписания лицея.

Точный порт логики парсинга из оригинального «Расписание_лицей.html»:
  - поиск строки-заголовка с классами (начинается с "5а");
  - дни недели в первом столбце (Пн..Сб), номер урока в столбце 0 или 1;
  - ячейка вида «Предмет1, Предмет2 (каб1, каб2)» -> names + rooms;
  - авто-определение типа файла: «учителя» (teachers) или «предметы» (subjects).

Поддерживаемые форматы: .xls (xlrd), .xlsx/.xlsm (openpyxl), .xml (Excel 2003
SpreadsheetML), .csv.
"""
from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
from datetime import datetime, time as datetime_time
from typing import Any

DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб"]
SERVICE = {"Классный час", "СФУ", "Экскурсия"}
SUBJECT_WORDS = [
    "алгебра", "геометрия", "математика", "русский", "литература", "физика",
    "химия", "биология", "география", "история", "обществознание", "ин.яз",
    "физ-ра", "информатика", "информ.", "технология", "изо", "музыка",
    "обзр", "черчение", "нзм", "нзд", "вероятность", "культура", "основы",
    "финансовая", "практика", "нестандартные", "поразительные", "спортивный",
    "инд.", "комп.", "программирование", "технический", "наглядная",
]

_CELL_RE = re.compile(r"^(.*?)\s*\(([^()]*)\)\s*$")
_TEACH_RE = re.compile(r"^[а-яё][а-яё-]+")
_INT_RE = re.compile(r"^\d{1,2}$")


class ParseError(Exception):
    """Ошибка разбора файла расписания."""


# ---------------------------------------------------------------- чтение файлов
def _rows_from_xls(buf: bytes) -> list[list[Any]]:
    import xlrd

    book = xlrd.open_workbook(file_contents=buf)
    sheet = book.sheet_by_index(0)
    return [[sheet.cell_value(r, c) for c in range(sheet.ncols)] for r in range(sheet.nrows)]


def _rows_from_xlsx(buf: bytes) -> list[list[Any]]:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(buf), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    return rows


def _rows_from_xml(buf: bytes) -> list[list[Any]]:
    """Excel 2003 XML (SpreadsheetML)."""
    ns = {"ss": "urn:schemas-microsoft-com:office:spreadsheet"}
    root = ET.fromstring(buf.decode("utf-8", errors="replace"))
    sheet = root.find(".//ss:Worksheet/ss:Table", ns)
    if sheet is None:
        # попробуем без пространства имён
        sheet = root.find(".//Worksheet/Table")
    if sheet is None:
        raise ParseError("XML-файл не похож на таблицу Excel (SpreadsheetML)")
    rows: list[list[Any]] = []
    for row_el in sheet:
        r_idx = row_el.get("{urn:schemas-microsoft-com:office:spreadsheet}Index")
        if r_idx:
            while len(rows) < int(r_idx) - 1:
                rows.append([])
        cells: list[Any] = []
        for cell_el in row_el:
            c_idx = cell_el.get("{urn:schemas-microsoft-com:office:spreadsheet}Index")
            if c_idx:
                while len(cells) < int(c_idx) - 1:
                    cells.append("")
            data_el = cell_el.find(
                "{urn:schemas-microsoft-com:office:spreadsheet}Data"
            )
            cells.append(data_el.text if data_el is not None and data_el.text else "")
        rows.append(cells)
    return rows


def _rows_from_csv(buf: bytes) -> list[list[Any]]:
    for enc in ("utf-8-sig", "cp1251", "utf-16"):
        try:
            text = buf.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = buf.decode("utf-8", errors="replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
    except csv.Error:
        dialect = csv.excel
    return [row for row in csv.reader(io.StringIO(text), dialect)]


def read_rows(buf: bytes, filename: str) -> list[list[Any]]:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    readers = {
        "xls": (_rows_from_xls, _rows_from_xlsx),
        "xlsx": (_rows_from_xlsx, _rows_from_xls),
        "xlsm": (_rows_from_xlsx, _rows_from_xls),
        "xml": (_rows_from_xml,),
        "csv": (_rows_from_csv,),
    }[ext if ext in {"xls", "xlsx", "xlsm", "xml", "csv"} else "xls"]
    last_exc: Exception | None = None
    for reader in readers:
        try:
            return reader(buf)
        except Exception as exc:  # noqa: BLE001 - пробуем следующий ридер
            last_exc = exc
    raise ParseError(f"Не удалось прочитать файл «{filename}»: {last_exc}")


# ------------------------------------------------------------------ разбор сетки
def _cell_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _unique_rooms(values: list[str]) -> list[str]:
    """Оставить первое написание каждого кабинета, игнорируя пробелы и регистр."""
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        room = re.sub(r"\s+", " ", value).strip()
        key = room.casefold()
        if room and key not in seen:
            result.append(room)
            seen.add(key)
    return result


def parse_cell(raw: str) -> dict:
    if not raw:
        return {"raw": "", "names": [], "rooms": []}
    m = _CELL_RE.match(raw)
    if m:
        names = [s.strip() for s in m.group(1).split(",") if s.strip()]
        rooms = _unique_rooms([s.strip() for s in m.group(2).split(",") if s.strip()])
        return {"raw": raw, "names": names, "rooms": rooms}
    return {"raw": raw, "names": [raw], "rooms": []}


def parse_grid(rows: list[list[Any]]) -> dict | None:
    def col(row: list[Any], i: int) -> str:
        return _cell_str(row[i]) if i < len(row) else ""

    h_idx = -1
    for i, row in enumerate(rows[:20]):
        if any(col(row, c) == "5а" for c in range(len(row))):
            h_idx = i
            break
    if h_idx < 0:
        return None

    header = [col(rows[h_idx], c) for c in range(len(rows[h_idx]))]
    classes = [c for c in header[header.index("5а"):] if c]

    lesson_col = 1
    for row in rows[h_idx + 1:]:
        first, second = col(row, 0), col(row, 1)
        if not first and not second:
            continue
        if _INT_RE.match(first):
            lesson_col = 0
        break
    data_start = lesson_col + 1

    grid: dict[str, dict[str, dict]] = {d: {} for d in DAYS}
    current_day = None
    for row in rows[h_idx + 1:]:
        first = col(row, 0)
        if first in DAYS:
            current_day = first
        try:
            lesson = int(float(col(row, lesson_col)))
        except (TypeError, ValueError):
            continue
        if not current_day:
            continue
        slot = {}
        for j, cls in enumerate(classes):
            slot[cls] = parse_cell(col(row, data_start + j))
        grid[current_day][str(lesson)] = slot
    return {"classes": classes, "grid": grid}


def detect_kind(data: dict) -> str:
    subj = teach = 0
    for day in DAYS:
        lessons = data["grid"].get(day) or {}
        for slot in lessons.values():
            for cell in slot.values():
                raw = cell["raw"]
                if not raw or raw in SERVICE:
                    continue
                m = _CELL_RE.match(raw)
                head = (m.group(1) if m else raw).strip().lower()
                if any(head.startswith(w) for w in SUBJECT_WORDS):
                    subj += 1
                elif _TEACH_RE.match(head):
                    teach += 1
    return "subjects" if subj > teach else "teachers"


def parse_schedule_file(buf: bytes, filename: str) -> tuple[str, dict]:
    """Возвращает (kind, data), kind = 'teachers' | 'subjects'."""
    rows = read_rows(buf, filename)
    data = parse_grid(rows)
    if data is None:
        raise ParseError("Не удалось разобрать структуру (не найдена строка классов «5а…»)")
    return detect_kind(data), data

# ------------------------------------------------------- расписание звонков
BELL_DAY_NAMES = {
    "понедельник": "Пн", "пн": "Пн",
    "вторник": "Вт", "вт": "Вт",
    "среда": "Ср", "ср": "Ср",
    "четверг": "Чт", "чт": "Чт",
    "пятница": "Пт", "пт": "Пт",
    "суббота": "Сб", "сб": "Сб",
    "воскресенье": "Вс", "вс": "Вс",
}
_BELL_LESSON_RE = re.compile(r"^(\d{1,2})(?:\.0+)?$")
_CLOCK_RE = re.compile(r"^(\d{1,2})(?:[:.](\d{1,2}))?(?::\d{1,2})?$")


def _bell_day(value: Any) -> str | None:
    day = _cell_str(value).strip().rstrip(".").casefold()
    return BELL_DAY_NAMES.get(day)


def _bell_clock(value: Any) -> str | None:
    """Нормализовать Excel/CSV время в HH:MM (включая формат 8.25 из CSV)."""
    if isinstance(value, datetime):
        value = value.time()
    if isinstance(value, datetime_time):
        return f"{value.hour:02d}:{value.minute:02d}"
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        # Excel хранит время как долю суток; поддерживаем также целое число часов.
        if isinstance(value, float) and 0 <= value < 1:
            total_minutes = round(value * 24 * 60)
            return f"{(total_minutes // 60) % 24:02d}:{total_minutes % 60:02d}"
        if float(value).is_integer() and 0 <= int(value) <= 23:
            return f"{int(value):02d}:00"
    text = _cell_str(value).strip()
    match = _CLOCK_RE.fullmatch(text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def parse_bell_schedule(rows: list[list[Any]]) -> dict:
    """Разобрать таблицу со сменами в первые четыре и следующие четыре колонки.

    Ожидаются два блока вида «День недели;Урок;Начало;Окончание», но второй
    блок не обязателен. День может быть указан только в первой строке дня.
    Специальные строки (например, «Классный час») намеренно не нумеруются.
    """
    shifts: dict[str, dict[str, dict[str, dict[str, str]]]] = {
        "1": {}, "2": {}
    }
    current_day: dict[str, str | None] = {"1": None, "2": None}

    def col(row: list[Any], index: int) -> Any:
        return row[index] if index < len(row) else ""

    for row in rows:
        for shift, offset in (("1", 0), ("2", 4)):
            day = _bell_day(col(row, offset))
            if day:
                current_day[shift] = day
            day = current_day[shift]
            lesson_text = _cell_str(col(row, offset + 1)).strip()
            lesson_match = _BELL_LESSON_RE.fullmatch(lesson_text)
            if not lesson_match or not day:
                continue

            start = _bell_clock(col(row, offset + 2))
            end = _bell_clock(col(row, offset + 3))
            if start is None or end is None:
                raise ParseError(
                    f"Не удалось прочитать время {lesson_match.group(1)}-го урока "
                    f"({start or 'начало'}–{end or 'окончание'})"
                )
            if end <= start:
                raise ParseError(
                    f"Время окончания должно быть позже начала: {start}–{end}"
                )
            lesson = str(int(lesson_match.group(1)))
            shifts[shift].setdefault(day, {})[lesson] = {"start": start, "end": end}

    lesson_count = sum(
        len(lessons)
        for day_data in shifts.values()
        for lessons in day_data.values()
    )
    if not lesson_count:
        raise ParseError(
            "Не найдены уроки с номером и временем. Проверьте столбцы "
            "«День недели», «Урок», «Начало», «Окончание»."
        )
    return {"shifts": shifts}


def parse_bell_schedule_file(buf: bytes, filename: str) -> dict:
    """Прочитать файл расписания звонков и вернуть смены/время уроков."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in {"xls", "xlsx", "xlsm", "xml", "csv"}:
        raise ParseError("Формат расписания звонков должен быть CSV, XLS, XLSX, XLSM или XML")
    return parse_bell_schedule(read_rows(buf, filename))
