from io import BytesIO
import pytest
from openpyxl import Workbook
from app.imports import parse_kug, parse_load
from app.validation import RuleError


def kug_file(value=3):
    book = Workbook()
    s = book.active
    s.title = "1 курс"
    s.append(["год набора 2026"])
    s.append(["Индекс", "Дисциплина", "октябрь"])
    s.cell(3, 3, "5-9")
    s.merge_cells("C3:D3")
    s.append(["ОП.01", "Анатомия теоретические занятия", value, 1])
    s.append([None, "Анатомия самостоятельная работа", 2, None])
    s.append([None, "Всего часов в неделю", 6, None])
    b = BytesIO()
    book.save(b)
    return b.getvalue()


def test_merged_week_is_summed_once_with_source_cells():
    sheet = parse_kug(kug_file(), "test.xlsx")["sheets"][0]
    assert len(sheet["weeks"]) == 1
    assert sheet["rows"][0]["hours"] == {"C:D": 4}
    assert sheet["rows"][0]["refs"]["C:D"] == ["C4", "D4"]
    assert sheet["rows"][1]["kind"] == "self_study"
    assert not sheet["errors"]


@pytest.mark.parametrize("value", [1.5, -2, "=SUM(1,2)", "#VALUE!"])
def test_invalid_or_uncached_hours_are_blockers(value):
    sheet = parse_kug(kug_file(value), "test.xlsx")["sheets"][0]
    assert sheet["errors"][0]["cell"] == "C4"
    assert sheet["errors"][0]["week_key"] == "C:D"


def test_non_excel_rejected():
    with pytest.raises(RuleError):
        parse_kug(b"bad archive", "test.xlsx")


def test_load_uncached_formula_is_not_silently_dropped():
    book = Workbook()
    s = book.active
    s.append(["часы"])
    s.append(["=1+1"])
    b = BytesIO()
    book.save(b)
    assert parse_load(b.getvalue(), "test.xlsx")["errors"]


def test_whitespace_is_an_empty_cell():
    sheet = parse_kug(kug_file(" "), "test.xlsx")["sheets"][0]
    assert not sheet["errors"]
    assert sheet["rows"][0]["hours"]["C:D"] == 1
