from datetime import timedelta
from io import BytesIO
from zipfile import ZipFile
import xml.etree.ElementTree as ET
import pytest
from app.domain import Allocation, Lesson
from app.scheduler import generate
from app.validation import RuleError, report, validate
from app.word_load import W, parse_word_load
from test_imports import kug_file


def word_file():
    root = ET.Element(W + "document")
    body = ET.SubElement(root, W + "body")

    def paragraph(parent, value):
        p = ET.SubElement(parent, W + "p")
        ET.SubElement(ET.SubElement(p, W + "r"), W + "t").text = value

    paragraph(body, "Распределение педнагрузки на 2026/2027 учебный год")
    paragraph(body, "I семестр 1 курс (база 9)")
    table = ET.SubElement(body, W + "tbl")
    for values in [
        ["", "Дисциплина", "теория", "практика", "Сам.р"],
        [
            "",
            "Анатомия",
            "14\n1-9ЛД126 Иванова А.Б.\n1-9ЛД226 Петрова В.Г.",
            "30+2\n1-9ЛД126 Иванова А.Б.",
            "26",
        ],
        [
            "",
            "Анатомия — отдельный раздел",
            "6\n1-9ЛД126\n1-9ЛД226\nИванова А.Б.",
            "",
            "",
        ],
        ["", "", "Консультация", "Промежуточная аттестация:", ""],
        ["", "Русский язык", "6х10", "6х10", ""],
    ]:
        row = ET.SubElement(table, W + "tr")
        for value in values:
            cell = ET.SubElement(row, W + "tc")
            for line in value.split("\n"):
                paragraph(cell, line)
    b = BytesIO()
    with ZipFile(b, "w") as z:
        z.writestr("word/document.xml", ET.tostring(root))
    return b.getvalue()


def entries():
    return parse_word_load(word_file(), "load.docx")["tables"][0]["entries"]


def test_word_preserves_original_hours_and_separates_kinds():
    e = entries()
    assert [r["kind"] for r in e] == [
        "theory",
        "practice",
        "self_study",
        "theory",
        "consultation",
        "assessment",
    ]
    assert e[1]["hours"] is None and e[1]["raw"].startswith("30+2\n")
    assert e[4]["hours"] is None  # multiplier is not per-group hours
    assert e[0]["hours"] == 14
    assert e[0]["assignments"] == [
        {"groups": ["1-9ЛД126"], "teachers": ["Иванова А.Б."], "joint": False},
        {"groups": ["1-9ЛД226"], "teachers": ["Петрова В.Г."], "joint": False},
    ]
    assert e[3]["warnings"]  # pending lines + trailing teacher need review
    assert len(parse_word_load(word_file(), "load.docx")["tables"][0]["rows"]) == 5


def test_group_parser_does_not_consume_surname_initial():
    from app.word_load import suggestions

    groups, teachers, *_ = suggestions("1-9ЛД226 Кадиева А.Б.\n1-9ЛД326кКадиева А.Б.")
    assert groups == ["1-9ЛД226", "1-9ЛД326к"]
    assert teachers == ["Кадиева А.Б."]


@pytest.mark.parametrize("raw", [b"bad", b"PK corrupt"])
def test_invalid_word_is_rejected(raw):
    with pytest.raises(RuleError):
        parse_word_load(raw, "bad.docx")


def test_word_dtd_is_rejected():
    b = BytesIO()
    with ZipFile(b, "w") as z:
        z.writestr("word/document.xml", b'<!DOCTYPE a [<!ENTITY x "test">]><a/>')
    with pytest.raises(RuleError):
        parse_word_load(b.getvalue(), "bad.docx")


def upload(client):
    r = client.post(
        "/api/imports?kind=term_load", files={"file": ("load.docx", word_file())}
    )
    assert r.status_code == 200
    return r.json()["id"]


def review():
    return {
        "acknowledged": True,
        "start_date": "2026-09-01",
        "end_date": "2026-12-31",
        "period": "I семестр",
        "groups": {
            n: {
                "program": "Лечебное дело",
                "course": 1,
                "base": "9",
                "entry_year": 2026,
            }
            for n in ("1-9ЛД126", "1-9ЛД226")
        },
        "entries": [
            {
                "key": entries()[0]["key"],
                "hours": 14,
                "kind": "theory",
                "assignments": entries()[0]["assignments"],
            }
        ],
    }


def test_word_confirmation_creates_period_load_without_weekly_hours(client):
    doc = upload(client)
    assert client.get(f"/api/imports/{doc}/original").content == word_file()
    repeated = client.post(
        "/api/imports?kind=term_load", files={"file": ("load.docx", word_file())}
    )
    assert repeated.json()["duplicate"]
    result = client.post(
        f"/api/imports/{doc}/term-load", json={"version": 0, "item": review()}
    )
    assert result.status_code == 200, result.text
    assert result.json()["count"] == 2
    s = client.get("/api/state").json()["state"]
    assert len(s["requirements"]) == 4 and len(s["allocations"]) == 2
    assert sorted(a["hours"] for a in s["allocations"].values()) == [14, 14]
    assert len({tuple(a["teacher_ids"]) for a in s["allocations"].values()}) == 2
    assert (
        client.post(
            f"/api/imports/{doc}/term-load", json={"version": 1, "item": review()}
        ).status_code
        == 422
    )
    assert client.get("/api/state").json()["version"] == 1


def test_invalid_cell_rolls_back_entire_batch_and_catalogs(client):
    doc = upload(client)
    item = review()
    item["entries"].append(
        {
            "key": entries()[1]["key"],
            "hours": 30,
            "kind": "practice",
            "assignments": entries()[0]["assignments"],
        }
    )
    r = client.post(f"/api/imports/{doc}/term-load", json={"version": 0, "item": item})
    assert r.status_code == 422 and "неоднозначным" in r.text
    s = client.get("/api/state").json()
    assert s["version"] == 0 and not s["state"]["allocations"]
    assert len(s["state"]["groups"]) == 2 and len(s["state"]["teachers"]) == 2
    item["entries"][1][
        "note"
    ] = "Включены только 30 часов практики; 2 часа зачёта отдельно"
    assert (
        client.post(
            f"/api/imports/{doc}/term-load", json={"version": 0, "item": item}
        ).status_code
        == 200
    )


def test_self_study_import_preserves_full_hours_and_responsible_teacher(client):
    doc = upload(client)
    item = review()
    item["entries"][0]["key"] = entries()[2]["key"]
    item["entries"][0]["kind"] = "self_study"
    item["entries"][0]["hours"] = 26
    assert (
        client.post(
            f"/api/imports/{doc}/term-load", json={"version": 0, "item": item}
        ).status_code
        == 200
    )
    allocations = list(client.get("/api/state").json()["state"]["allocations"].values())
    assert len(allocations) == 2
    assert all(a["kind"] == "self_study" and a["hours"] == 26 for a in allocations)
    assert len({tuple(a["teacher_ids"]) for a in allocations}) == 2


def allocation(state, **changes):
    r = state.requirements["n1"]
    return Allocation(
        id="a1",
        subject_id=r.subject_id,
        group_ids=r.group_ids,
        teacher_ids=r.teacher_ids,
        start_date=r.week,
        end_date=r.week + timedelta(days=13),
        hours=4,
        **changes,
    )


def test_period_cap_dates_and_assignments_are_enforced(state):
    a = allocation(state)
    state.allocations[a.id] = a
    r = state.requirements["n1"]
    r.allocation_id = a.id
    validate(state)
    next_week = r.model_copy(
        update={"id": "next", "week": r.week + timedelta(days=7), "hours": 1}
    )
    state.requirements[next_week.id] = next_week
    with pytest.raises(RuleError, match="семестровые"):
        validate(state)
    del state.requirements[next_week.id]
    a.end_date = r.week + timedelta(days=1)
    result = generate(state, r.week, [])
    assert result["status"] in {"optimal", "feasible"}
    assert all(
        Lesson.model_validate(l).day <= a.end_date
        for l in result["lessons"]
        if l["requirement_id"] == r.id
    )
    a.teacher_ids = ["t2"]
    with pytest.raises(RuleError, match="назначения"):
        validate(state)


def test_joint_teaching_reserves_every_teacher(state):
    r = state.requirements["n1"]
    r.teacher_ids = ["t1", "t2"]
    r.teacher_mode = "together"
    result = generate(state, r.week, [])
    assert result["status"] in {"optimal", "feasible"}
    state.lessons = {l["id"]: Lesson.model_validate(l) for l in result["lessons"]}
    validate(state)
    joint = next(l for l in state.lessons.values() if l.requirement_id == r.id)
    assert joint.teacher_ids == ["t1", "t2"]
    joint.teacher_ids = ["t1"]
    with pytest.raises(RuleError, match="совместном"):
        validate(state)


def test_kug_uses_different_period_teachers_and_checks_per_group_coverage(client):
    state = client.get("/api/state").json()["state"]
    week = state["requirements"]["n1"]["week"]
    for i in (1, 2):
        r = client.put(
            f"/api/allocations/a{i}",
            json={
                "version": i - 1,
                "item": {
                    "subject_id": "s1",
                    "group_ids": [f"g{i}"],
                    "teacher_ids": [f"t{i}"],
                    "start_date": week,
                    "end_date": week,
                    "hours": 4,
                },
            },
        )
        assert r.status_code == 200, r.text
    doc = client.post(
        "/api/imports?kind=kug", files={"file": ("kug.xlsx", kug_file())}
    ).json()["id"]
    item = {
        "acknowledged": True,
        "sheet_key": "0",
        "week_key": "C:D",
        "week": week,
        "group_ids": ["g1", "g2"],
        "rows": [
            {
                "row_key": "4",
                "kind": "theory",
                "room_ids": ["r1"],
                "allocations": [{"allocation_id": "a1", "hours": 4}],
            },
            {"row_key": "5", "teacher_ids": ["t1"], "kind": "self_study"},
        ],
    }
    assert (
        client.post(
            f"/api/imports/{doc}/kug", json={"version": 2, "item": item}
        ).status_code
        == 422
    )
    item["rows"][0]["allocations"].append({"allocation_id": "a2", "hours": 4})
    r = client.post(f"/api/imports/{doc}/kug", json={"version": 2, "item": item})
    assert r.status_code == 200, r.text
    rows = [
        r
        for r in client.get("/api/state").json()["state"]["requirements"].values()
        if r["allocation_id"]
    ]
    assert {tuple(r["teacher_ids"]) for r in rows} == {("t1",), ("t2",)}
    assert all(r["hours"] == 4 for r in rows)


def test_unlinked_period_load_is_reported(state):
    a = allocation(state)
    state.allocations[a.id] = a
    assert any("семестровой" in s for s in report(state)["warnings"])


def test_period_overlap_for_same_student_unit_is_rejected(state):
    a = allocation(state)
    state.allocations[a.id] = a
    b = a.model_copy(update={"id": "a2", "group_ids": ["g1"]})
    state.allocations[b.id] = b
    with pytest.raises(RuleError, match="Пересекающиеся"):
        validate(state)


def test_allocation_change_updates_linked_rows_atomically(client):
    s = client.get("/api/state").json()["state"]
    r = s["requirements"]["n1"]
    a = {
        "subject_id": r["subject_id"],
        "group_ids": r["group_ids"],
        "teacher_ids": r["teacher_ids"],
        "hours": 4,
        "start_date": r["week"],
        "end_date": r["week"],
    }
    assert (
        client.put("/api/allocations/a1", json={"version": 0, "item": a}).status_code
        == 200
    )
    r["allocation_id"] = "a1"
    assert (
        client.put("/api/requirements/n1", json={"version": 1, "item": r}).status_code
        == 200
    )
    a["teacher_ids"] = ["t2"]
    assert (
        client.put("/api/allocations/a1", json={"version": 2, "item": a}).status_code
        == 422
    )
    assert client.get("/api/state").json()["version"] == 2
    a["update_linked"] = True
    assert (
        client.put("/api/allocations/a1", json={"version": 2, "item": a}).status_code
        == 200
    )
    assert client.get("/api/state").json()["state"]["requirements"]["n1"][
        "teacher_ids"
    ] == ["t2"]
    a["hours"] = 3
    assert (
        client.put("/api/allocations/a1", json={"version": 3, "item": a}).status_code
        == 422
    )
    assert client.get("/api/state").json()["state"]["allocations"]["a1"]["hours"] == 4


def test_merged_word_cells_preserve_grid_and_invalid_spans_reject():
    with ZipFile(BytesIO(word_file())) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    row = root.find(".//" + W + "tbl").findall(W + "tr")[2]
    cells = row.findall(W + "tc")
    row.remove(cells[0])
    props = ET.SubElement(cells[1], W + "tcPr")
    span = ET.SubElement(props, W + "gridSpan", {W + "val": "2"})

    def raw():
        b = BytesIO()
        with ZipFile(b, "w") as z:
            z.writestr("word/document.xml", ET.tostring(root))
        return b.getvalue()

    d = parse_word_load(raw(), "merged.docx")
    assert d["tables"][0]["rows"][2][0]["span"] == 2
    assert d["tables"][0]["entries"][3]["hours"] == 6
    span.set(W + "val", "wrong")
    with pytest.raises(RuleError):
        parse_word_load(raw(), "bad.docx")
