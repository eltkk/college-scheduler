from collections import defaultdict
from datetime import timedelta
from io import BytesIO
import re
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from .domain import KIND_LABELS
from .imports import LOAD_HEADERS


def safe(value):
    value = str(value)
    return "'" + value if value[:1] in {"=", "+", "-", "@"} else value


def clock(value):
    return f"{value//60:02}:{value%60:02}"


def bytes_for(book):
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def load_template():
    book = Workbook()
    sheet = book.active
    sheet.title = "Нагрузка"
    sheet.append(list(LOAD_HEADERS.values()))
    sheet.append(
        [
            "Группа 1",
            "Анатомия",
            "Иванова И.И.",
            "Кабинет 210",
            "2026-10-05",
            4,
            "practice",
            2,
        ]
    )
    for col in range(1, 9):
        sheet.column_dimensions[get_column_letter(col)].width = 25
    notes = book.create_sheet("Инструкция")
    for line in [
        "Пример во второй строке замените реальными данными.",
        "Неделя: дата понедельника. Часы: целые академические часы.",
        "Вид: theory, practice, consultation, assessment, training, coursework.",
        "Блок: длительность непрерывного занятия в академических часах.",
        "Несколько групп/преподавателей/помещений разделяйте точкой с запятой.",
        "Несколько преподавателей в строке: разрешённые альтернативы для автоматического назначения.",
        "Для разных практических групп используйте разные строки.",
    ]:
        notes.append([line])
    notes.column_dimensions["A"].width = 110
    return bytes_for(book)


def export_schedule(state, week, group_ids=None):
    book = Workbook()
    book.remove(book.active)
    groups = [g for g in state.groups.values() if not group_ids or g.id in group_ids]
    partitions = defaultdict(list)
    for group in groups:
        partitions[group.program, group.course, group.base].append(group)
    if not partitions:
        partitions["Колледж", 0, ""] = []
    thin = Side(style="thin", color="9CA3AF")
    for index, ((program, course, base), columns) in enumerate(partitions.items(), 1):
        columns.sort(key=lambda g: (g.stream, g.name))
        title = re.sub(r"[\\/*?:\[\]]", " ", f"{index} {program or 'Группы'} {course}")[
            :31
        ]
        sheet = book.create_sheet(title)
        last = max(3, 2 + len(columns))
        sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last)
        sheet.cell(
            1,
            1,
            safe(
                f"{state.settings.name}: {week:%d.%m.%Y} — {(week+timedelta(days=6)):%d.%m.%Y}"
            ),
        )
        sheet.cell(1, 1).font = Font(bold=True, size=14)
        sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=last)
        sheet.cell(2, 1, safe(f"{program}, курс {course}, база {base} классов"))
        sheet.append(["День", "Время"] + [safe(g.name) for g in columns])
        for col in range(1, last + 1):
            sheet.cell(3, col).font = Font(bold=True, color="FFFFFF")
            sheet.cell(3, col).fill = PatternFill("solid", fgColor="334155")
        row = 4
        for weekday in state.settings.study_days:
            day = week + timedelta(days=weekday)
            day_lessons = [l for l in state.lessons.values() if l.day == day]
            boundaries = sorted(
                set(
                    [x for b in state.settings.bells for x in (b.start, b.end)]
                    + [x for l in day_lessons for x in (l.start, l.end)]
                )
            )
            intervals = [
                (a, b)
                for a, b in zip(boundaries, boundaries[1:])
                if any(bell.start <= a < bell.end for bell in state.settings.bells)
                or any(l.start <= a < l.end for l in day_lessons)
            ]
            lookup = {}
            for start, end in intervals:
                sheet.cell(
                    row,
                    1,
                    safe(
                        f"{['Пн','Вт','Ср','Чт','Пт','Сб','Вс'][weekday]} {day:%d.%m}"
                    ),
                )
                sheet.cell(row, 2, f"{clock(start)}–{clock(end)}")
                for c, group in enumerate(columns, 3):
                    relevant = []
                    from .validation import leaf_groups

                    leaves = leaf_groups(state, [group.id])
                    for l in day_lessons:
                        if l.start <= start < l.end and leaves & leaf_groups(
                            state, l.group_ids
                        ):
                            relevant.append(l)
                    texts = []
                    for l in relevant:
                        teachers = ", ".join(
                            state.teachers[t].name for t in l.teacher_ids
                        )
                        room = state.rooms[l.room_id]
                        texts.append(
                            f"{state.subjects[l.subject_id].name}\n{KIND_LABELS[l.kind]} · {teachers}\n{room.name}{' · '+room.building if room.building else ''}{'\n'+l.note if l.note else ''}"
                        )
                    sheet.cell(row, c, safe("\n\n".join(texts)))
                    lookup[row, c] = tuple(l.id for l in relevant)
                sheet.row_dimensions[row].height = 92
                row += 1
            # Merge rectangular runs only when the exact same shared event occupies them.
            taken = set()
            first = row - len(intervals)
            for r in range(first, row):
                for c in range(3, last + 1):
                    key = lookup.get((r, c), ())
                    if len(key) != 1 or (r, c) in taken:
                        continue
                    right = c
                    while (
                        right < last
                        and lookup.get((r, right + 1)) == key
                        and (r, right + 1) not in taken
                    ):
                        right += 1
                    bottom = r
                    while bottom + 1 < row and all(
                        lookup.get((bottom + 1, x)) == key
                        and (bottom + 1, x) not in taken
                        for x in range(c, right + 1)
                    ):
                        bottom += 1
                    if right > c or bottom > r:
                        sheet.merge_cells(
                            start_row=r,
                            start_column=c,
                            end_row=bottom,
                            end_column=right,
                        )
                    taken.update(
                        (y, x)
                        for y in range(r, bottom + 1)
                        for x in range(c, right + 1)
                    )
        for cells in sheet:
            for cell in cells:
                cell.alignment = Alignment(
                    horizontal="center", vertical="center", wrap_text=True
                )
                cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)
        sheet.column_dimensions["A"].width = 14
        sheet.column_dimensions["B"].width = 17
        for col in range(3, last + 1):
            sheet.column_dimensions[get_column_letter(col)].width = 38
        sheet.freeze_panes = "C4"
        sheet.print_title_rows = "1:3"
        sheet.print_options.horizontalCentered = True
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.paperSize = sheet.PAPERSIZE_A3
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.print_area = f"A1:{get_column_letter(last)}{max(3,row-1)}"
    summary = book.create_sheet("Часы")
    summary.append(["Предмет", "Группы", "Вид", "План", "Размещено", "Остаток"])
    for req in state.requirements.values():
        if req.week == week and (not group_ids or set(req.group_ids) & set(group_ids)):
            actual = sum(
                l.hours for l in state.lessons.values() if l.requirement_id == req.id
            )
            summary.append(
                [
                    safe(state.subjects[req.subject_id].name),
                    safe(", ".join(state.groups[g].name for g in req.group_ids)),
                    KIND_LABELS[req.kind],
                    req.hours,
                    actual,
                    req.hours - actual,
                ]
            )
    for col, width in enumerate([60, 35, 25, 15, 18, 15], 1):
        summary.column_dimensions[get_column_letter(col)].width = width
    return bytes_for(book)
