from io import BytesIO
import pytest
from openpyxl import Workbook
from app.imports import classify, parse_kug, parse_load
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
    assert sheet["weeks"][0]["hours"] == 6
    assert sheet["weeks"][0]["declared_hours"] == 6
    assert not sheet["weeks"][0]["warnings"]


@pytest.mark.parametrize("value", [1.5, -2, True, False, "=SUM(1,2)", "#VALUE!"])
def test_invalid_or_uncached_hours_are_blockers(value):
    sheet = parse_kug(kug_file(value), "test.xlsx")["sheets"][0]
    assert sheet["errors"][0]["cell"] == "C4"
    assert sheet["errors"][0]["week_key"] == "C:D"


def test_non_excel_rejected():
    with pytest.raises(RuleError):
        parse_kug(b"bad archive", "test.xlsx")


def test_consultation_before_exam_is_not_exam_hours():
    assert classify("Русский язык (консультации к экзамену)") == "consultation"


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


def test_kug_footer_mismatch_is_visible_without_rewriting_source_hours():
    sheet = parse_kug(kug_file(1), "test.xlsx")["sheets"][0]
    week = sheet["weeks"][0]
    assert week["hours"] == 4 and week["declared_hours"] == 6
    assert "не совпадает" in week["warnings"][0]
    assert sheet["rows"][0]["hours"]["C:D"] == 2


def test_term_total_under_week_heading_cannot_be_confirmed(client):
    raw = kug_file(609)
    sheet = parse_kug(raw, "test.xlsx")["sheets"][0]
    assert sheet["weeks"][0]["hours"] == 612
    assert sheet["errors"][0]["week_key"] == "C:D"
    assert "итогом семестра" in sheet["errors"][0]["message"]
    doc = client.post(
        "/api/imports?kind=kug", files={"file": ("test.xlsx", raw)}
    ).json()["id"]
    before = client.get("/api/state").json()
    response = client.post(
        f"/api/imports/{doc}/kug",
        json={
            "version": before["version"],
            "item": {
                "acknowledged": True,
                "sheet_key": "0",
                "week_key": "C:D",
                "week": before["state"]["requirements"]["n1"]["week"],
                "group_ids": ["g1"],
            },
        },
    )
    assert response.status_code == 422
    assert client.get("/api/state").json() == before
    # Existing previews must receive the same protection after an upgrade.
    from app.db import ImportDocument, SessionLocal

    with SessionLocal() as db:
        document = db.get(ImportDocument, doc)
        preview = {**document.preview}
        preview["sheets"] = [{**preview["sheets"][0], "errors": []}]
        document.preview = preview
        db.commit()
    legacy = client.post(
        f"/api/imports/{doc}/kug",
        json={
            "version": before["version"],
            "item": {
                "acknowledged": True,
                "sheet_key": "0",
                "week_key": "C:D",
                "week": before["state"]["requirements"]["n1"]["week"],
                "group_ids": ["g1"],
            },
        },
    )
    assert legacy.status_code == 422 and "168" in legacy.text
    assert client.get("/api/state").json() == before
