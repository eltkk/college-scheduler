import hashlib
import io
import re
import zipfile
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from .validation import RuleError

MONTHS = [
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
]


def check_xlsx(raw):
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
        infos = archive.infolist()
        if len(infos) > 5000 or sum(x.file_size for x in infos) > 80 * 1024 * 1024:
            raise RuleError("Excel содержит слишком большой объём распакованных данных")
        if "xl/workbook.xml" not in archive.namelist():
            raise RuleError("Нужен файл Excel .xlsx")
    except zipfile.BadZipFile as exc:
        raise RuleError("Повреждённый файл Excel") from exc


def classify(name):
    v = name.casefold()
    if "самосто" in v:
        return "self_study"
    if "производствен" in v or "учебная" in v and "практик" in v:
        return "training"
    if any(x in v for x in ["аттестац", "экзамен", "зачет", "зачёт", "гиа"]):
        return "assessment"
    if "консульт" in v:
        return "consultation"
    if "курсов" in v or "курсова" in v:
        return "coursework"
    if "практич" in v:
        return "practice"
    if "теорет" in v:
        return "theory"
    return "unknown"


def parse_kug(raw, filename):
    check_xlsx(raw)
    try:
        book = load_workbook(io.BytesIO(raw), data_only=False, keep_links=False)
        cached = load_workbook(io.BytesIO(raw), data_only=True, keep_links=False)
    except Exception as exc:
        raise RuleError("Не удалось прочитать XLSX") from exc
    result = {
        "format": "kug",
        "filename": filename,
        "digest": hashlib.sha256(raw).hexdigest(),
        "sheets": [],
    }
    for index, sheet in enumerate(book):
        warnings = []
        errors = []
        if sheet.max_row > 2000 or sheet.max_column > 150:
            raise RuleError("Лист КУГ слишком большой для поддерживаемого формата")
        header = next(
            (
                r
                for r in range(1, min(25, sheet.max_row) + 1)
                if str(sheet.cell(r, 1).value).strip().casefold() == "индекс"
            ),
            None,
        )
        if header is None:
            result["sheets"].append(
                {
                    "key": str(index),
                    "name": sheet.title,
                    "warnings": ["Не найдена шапка КУГ"],
                    "rows": [],
                    "weeks": [],
                    "metadata": [],
                }
            )
            continue
        totals_row = next(
            (
                r
                for r in range(header + 2, sheet.max_row + 1)
                if "всего часов в неделю" in str(sheet.cell(r, 2).value).casefold()
            ),
            sheet.max_row + 1,
        )
        metadata = [
            str(c.value)
            for row in sheet.iter_rows(min_row=1, max_row=header - 1)
            for c in row
            if c.value is not None
        ]
        cohorts = set(re.findall(r"год\s+набора\s+(\d{4})", " ".join(metadata), re.I))
        if len(cohorts) > 1:
            warnings.append(
                "В заголовках указаны разные годы набора: " + ", ".join(sorted(cohorts))
            )
        name_course = re.search(r"(\d)\s*курс", sheet.title)
        header_courses = re.findall(r"(\d)\s*курс", " ".join(metadata), re.I)
        if (
            name_course
            and header_courses
            and any(x != name_course[1] for x in header_courses)
        ):
            warnings.append("Курс в названии листа отличается от курса в заголовке")
        warnings.append(
            "Подтвердите привязку листа к группам, учебному году и реальным датам недель"
        )
        spans = []
        col = 3
        month = ""
        while col <= sheet.max_column:
            top = str(sheet.cell(header, col).value or "").strip()
            low = str(sheet.cell(header + 1, col).value or "").strip()
            if top.casefold() in MONTHS:
                month = top
            if "всего часов" in top.casefold():
                break
            if "часов за семестр" in top.casefold():
                col += 1
                continue
            label = (
                low
                if re.search(r"\d\s*[-–]\s*\d", low)
                else top if re.search(r"\d.*[-–].*\d", top) else ""
            )
            if not label:
                col += 1
                continue
            end = col
            for merged in sheet.merged_cells.ranges:
                if merged.min_col == col and (
                    merged.min_row == header + 1
                    or merged.min_row == header
                    and merged.max_row >= header + 1
                ):
                    end = merged.max_col
                    break
            key = f"{get_column_letter(col)}:{get_column_letter(end)}"
            spans.append(
                {
                    "key": key,
                    "label": f"{month}: {label}" if label == low else label,
                    "start_col": col,
                    "end_col": end,
                }
            )
            col = end + 1
        rows = []
        current_code = ""
        for r in range(header + 2, totals_row):
            code = sheet.cell(r, 1).value
            if code is not None:
                current_code = str(code).strip()
            name = sheet.cell(r, 2).value
            if not name:
                continue
            name = str(name).strip()
            hours = {}
            refs = {}
            for span in spans:
                value = 0
                cells = []
                for c in range(span["start_col"], span["end_col"] + 1):
                    cell = sheet.cell(r, c)
                    raw_value = cell.value
                    if isinstance(raw_value, str) and not raw_value.strip():
                        raw_value = None
                    v = (
                        cached[sheet.title].cell(r, c).value
                        if cell.data_type == "f"
                        else raw_value
                    )
                    if raw_value is not None and (
                        v is None or not isinstance(v, (int, float))
                    ):
                        errors.append(
                            {
                                "week_key": span["key"],
                                "cell": cell.coordinate,
                                "message": f"Не прочитаны часы: {str(raw_value)[:60]}",
                            }
                        )
                    if isinstance(v, (int, float)):
                        if v < 0 or int(v) != v:
                            errors.append(
                                {
                                    "week_key": span["key"],
                                    "cell": cell.coordinate,
                                    "message": "Часы должны быть целыми и неотрицательными",
                                }
                            )
                        elif v:
                            value += int(v)
                            cells.append(cell.coordinate)
                if value:
                    hours[span["key"]] = value
                    refs[span["key"]] = cells
            if hours:
                rows.append(
                    {
                        "key": str(r),
                        "code": current_code,
                        "name": name,
                        "kind": classify(name),
                        "hours": hours,
                        "refs": refs,
                    }
                )
        result["sheets"].append(
            {
                "key": str(index),
                "name": sheet.title,
                "metadata": metadata,
                "weeks": spans,
                "rows": rows,
                "warnings": list(dict.fromkeys(warnings)),
                "errors": errors,
            }
        )
    return result


LOAD_HEADERS = {
    "group": "группа",
    "subject": "предмет",
    "teacher": "преподаватель",
    "room": "кабинет",
    "week": "неделя",
    "hours": "часы",
    "kind": "вид",
    "block_hours": "блок",
}


def parse_load(raw, filename):
    check_xlsx(raw)
    try:
        book = load_workbook(io.BytesIO(raw), data_only=True, keep_links=False)
        source = load_workbook(io.BytesIO(raw), data_only=False, keep_links=False)
    except Exception as exc:
        raise RuleError("Не удалось прочитать XLSX нагрузки") from exc
    sheet = book.active
    if sheet.max_row > 10000 or sheet.max_column > 100:
        raise RuleError("Слишком большой лист нагрузки")
    headers = [str(c.value or "").strip() for c in sheet[1]]
    rows = [
        {
            str(i): c.value.isoformat() if hasattr(c.value, "isoformat") else c.value
            for i, c in enumerate(row)
            if c.value is not None
        }
        for row in sheet.iter_rows(min_row=2)
        if any(c.value is not None for c in row)
    ]
    guessed = {
        field: str(i)
        for field, label in LOAD_HEADERS.items()
        for i, h in enumerate(headers)
        if h.casefold() == label
    }
    errors = [
        f"{c.coordinate}: формула не рассчитана или ошибка Excel"
        for row in source.active.iter_rows(min_row=2)
        for c in row
        if c.data_type == "e"
        or c.data_type == "f"
        and sheet[c.coordinate].value is None
    ]
    return {
        "format": "load",
        "filename": filename,
        "digest": hashlib.sha256(raw).hexdigest(),
        "headers": headers,
        "rows": rows,
        "mapping": guessed,
        "errors": errors,
    }
