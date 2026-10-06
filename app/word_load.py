"""Lossless DOCX preview. Extracted names/hours are suggestions, never a schedule."""

import hashlib
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from .validation import RuleError

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
GROUP = re.compile(
    r"(?<![\w])\d{1,2}\s*(?:-\s*9\s*)?(?:АкД|АД|ЛД|А)\s*\d{3,4}(?:\s*(?-i:[бкс])(?!(?-i:[а-яё])))?",
    re.I,
)
TEACHER = re.compile(r"[А-ЯЁ][а-яё-]{2,}\s*[А-ЯЁ]\s*\.+\s*[А-ЯЁ]\s*\.*")


def grid_number(element, default):
    try:
        number = (
            int(element.get(W + "val", str(default)))
            if element is not None
            else default
        )
    except (ValueError, TypeError) as exc:
        raise RuleError("Неверное объединение или отступ ячеек Word") from exc
    if not 0 <= number <= 100:
        raise RuleError("Неверная ширина таблицы Word")
    return number


def text_of(element):
    parts = []
    for node in element.iter():
        if node.tag == W + "t":
            parts.append(node.text or "")
        elif node.tag in (W + "br", W + "cr"):
            parts.append("\n")
        elif node.tag == W + "tab":
            parts.append("\t")
    return "".join(parts).strip()


def column_kind(label):
    v = re.sub(r"[\s./]", "", label.casefold())
    if "теори" in v:
        return "theory"
    if "практи" in v:
        return "practice"
    if "конс" in v:
        return "consultation"
    if "сам" in v or v in ("ср",):
        return "self_study"
    if any(x in v for x in ("экз", "зач", "аттест", "па", "з/д", "зд", "диф")):
        return "assessment"
    return "unknown"


def subject_kind(name):
    v = name.casefold()
    if "самостоятель" in v:
        return "self_study"
    if "производствен" in v or "учебная" in v or re.match(r"\s*(уп|пп)\b", v):
        return "training"
    if "курсов" in v or "курсова" in v:
        return "coursework"
    if "аттестаци" in v or "экзамен" in v or "гиа" in v:
        return "assessment"
    return None


def suggestions(value):
    # Names are not fuzzy-merged, misspellings and cohort codes remain visible.
    groups = list(
        dict.fromkeys(re.sub(r"\s+", "", m.group()) for m in GROUP.finditer(value))
    )
    teachers = list(
        dict.fromkeys(
            re.sub(r"\s+", " ", m.group()).strip() for m in TEACHER.finditer(value)
        )
    )
    assignments = []
    pending = []
    inherited = False
    for line in value.splitlines():
        gs = list(
            dict.fromkeys(re.sub(r"\s+", "", m.group()) for m in GROUP.finditer(line))
        )
        ts = list(
            dict.fromkeys(
                re.sub(r"\s+", " ", m.group()).strip() for m in TEACHER.finditer(line)
            )
        )
        if gs:
            pending.extend(gs)
        if ts and pending:
            assignments.append({"groups": list(dict.fromkeys(pending)), "teachers": ts})
            inherited |= not gs or len(pending) != len(gs)
            pending = []
    return groups, teachers, assignments, pending, inherited


def parse_word_load(raw: bytes, filename: str):
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if len(infos) > 5000 or sum(x.file_size for x in infos) > 80 * 1024 * 1024:
                raise RuleError(
                    "Word содержит слишком большой объём распакованных данных"
                )
            xml = archive.read("word/document.xml")
        if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
            raise RuleError("Неподдерживаемая структура XML в Word")
        root = ET.fromstring(xml)
    except (zipfile.BadZipFile, KeyError, ET.ParseError, RuntimeError) as exc:
        raise RuleError("Не удалось прочитать документ .docx") from exc
    body = root.find(W + "body")
    if body is None:
        raise RuleError("В Word не найден текст документа")
    result = {
        "format": "term_load",
        "filename": filename,
        "digest": hashlib.sha256(raw).hexdigest(),
        "paragraphs": [],
        "tables": [],
    }
    context = ""
    for block in body:
        if block.tag == W + "p":
            value = text_of(block)
            if value:
                result["paragraphs"].append(value)
                if "семестр" in value.casefold():
                    context = value
        elif block.tag == W + "tbl":
            rows = []
            for tr in block.findall(W + "tr"):
                cells = []
                before = tr.find(W + "trPr/" + W + "gridBefore")
                col = grid_number(before, 0)
                for tc in tr.findall(W + "tc"):
                    span = tc.find(W + "tcPr/" + W + "gridSpan")
                    merge = tc.find(W + "tcPr/" + W + "vMerge")
                    width = grid_number(span, 1)
                    if not 1 <= width <= 100 or col + width > 100:
                        raise RuleError("Слишком широкая таблица Word")
                    value = "\n".join(text_of(p) for p in tc.findall(W + "p")).strip()
                    cells.append(
                        {
                            "column": col,
                            "span": width,
                            "text": value,
                            "merge": (
                                merge.get(W + "val", "continue")
                                if merge is not None
                                else None
                            ),
                        }
                    )
                    col += width
                rows.append(cells)
            if len(rows) > 2000 or len(result["tables"]) >= 100:
                raise RuleError("Слишком много строк или таблиц Word")
            if not rows:
                continue
            header = rows[0]
            subject_col = next(
                (c["column"] for c in header if "дисциплин" in c["text"].casefold()), 1
            )
            labels = {
                i: c["text"]
                for c in header
                for i in range(c["column"], c["column"] + c["span"])
            }
            key = str(len(result["tables"]))
            entries = []
            section = ""
            for row_index, row in enumerate(rows[1:], 2):
                named = next(
                    (
                        c
                        for c in row
                        if c["column"] <= subject_col < c["column"] + c["span"]
                    ),
                    None,
                )
                name = named["text"].strip() if named else ""
                if not name:
                    if any("консультаци" in c["text"].casefold() for c in row):
                        labels.update(
                            {
                                i: c["text"]
                                for c in row
                                for i in range(c["column"], c["column"] + c["span"])
                                if c["text"]
                            }
                        )
                    continue  # empty totals rows remain in raw table
                if "промежуточная аттестация" in name.casefold():
                    section = "assessment"
                    continue
                sk = subject_kind(name)
                for cell in row:
                    if cell is named or not cell["text"] or cell["merge"] == "continue":
                        continue
                    value = cell["text"]
                    head = next(
                        (s.strip() for s in value.splitlines() if s.strip()), ""
                    )
                    hours = int(head) if re.fullmatch(r"\d{1,4}", head) else None
                    if hours == 0:
                        continue
                    gs, ts, assignments, pending, inherited = suggestions(value)
                    # A punctuation placeholder is not a workload cell.
                    if (
                        hours is None
                        and not re.search(r"\d", value)
                        and not gs
                        and not ts
                    ):
                        continue
                    kind = (
                        sk
                        or (section if named["span"] > 1 else None)
                        or column_kind(labels.get(cell["column"], ""))
                    )
                    warnings = []
                    if hours is None:
                        warnings.append(
                            "Часы не являются одним числом. Разделите виды нагрузки и укажите подтверждённые часы."
                        )
                    if not gs or not ts or pending:
                        warnings.append(
                            "Не все группы и преподаватели определены. Проверьте назначения."
                        )
                    if inherited:
                        warnings.append(
                            "ФИО стоит после нескольких строк групп. Область назначения требует проверки."
                        )
                    if len(ts) > 1:
                        warnings.append(
                            "Проверьте распределение преподавателей; совместное ведение задаётся явно."
                        )
                    if any(int(re.match(r"\d+", g)[0]) > 6 for g in gs):
                        warnings.append("Необычный номер курса в обозначении группы.")
                    entries.append(
                        {
                            "key": f"{key}:{row_index}:{cell['column'] + 1}",
                            "row": row_index,
                            "column": cell["column"] + 1,
                            "subject": name,
                            "label": labels.get(cell["column"], ""),
                            "kind": kind,
                            "hours": hours,
                            "raw": value,
                            "groups": gs,
                            "teachers": ts,
                            "assignments": assignments,
                            "warnings": warnings,
                        }
                    )
            result["tables"].append(
                {
                    "key": key,
                    "context": context,
                    "rows": rows,
                    "entries": entries,
                    "warnings": [
                        "Подтвердите даты семестра, группы, преподавателей и объединение занятий. Часы относятся к семестру, а не к неделе."
                    ],
                }
            )
    if not result["tables"]:
        raise RuleError("В документе нет таблиц нагрузки")
    result["academic_years"] = sorted(
        set(re.findall(r"20\d{2}\s*/\s*20\d{2}", " ".join(result["paragraphs"])))
    )
    return result
