from collections import defaultdict
from datetime import timedelta
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app.domain import Allocation, Lesson, Requirement, State, college_profile
from app.export import export_schedule
from app.scheduler import generate, periods
from app.validation import RuleError, report, validate
from app.word_load import suggestions
from test_imports import kug_file


def regular_week(state):
    week = state.requirements["n1"].week
    state.settings = college_profile()
    state.settings.confirmed = True
    state.requirements = {
        "class": Requirement(
            id="class",
            subject_id="s1",
            group_ids=["g1"],
            teacher_ids=["t1"],
            room_ids=["r1"],
            week=week,
            hours=32,
        ),
        "self": Requirement(
            id="self",
            subject_id="s1",
            group_ids=["g1"],
            teacher_ids=["t1"],
            week=week,
            kind="self_study",
            hours=4,
        ),
    }
    return week


def test_full_week_includes_self_study_and_exported_responsible_teacher(state):
    week = regular_week(state)
    result = generate(state, week, ["g1"])
    assert result["status"] in {"optimal", "feasible"}, result
    state.lessons = {raw["id"]: Lesson.model_validate(raw) for raw in result["lessons"]}
    daily = defaultdict(int)
    for lesson in state.lessons.values():
        daily[lesson.day] += lesson.hours
    assert sum(daily.values()) == 36 and max(daily.values()) <= 10
    self_work = [l for l in state.lessons.values() if l.kind == "self_study"]
    assert sum(l.hours for l in self_work) == 4
    assert all(l.teacher_ids == ["t1"] and l.room_id is None for l in self_work)
    validate(state)
    check = report(state, week)
    assert check["complete"], check
    assert check["group_hours"] == [
        {
            "group_id": "g1",
            "group": "Группа 1",
            "week": str(week),
            "planned": 36,
            "scheduled": 36,
            "target": 36,
        }
    ]
    book = load_workbook(BytesIO(export_schedule(state, week)))
    texts = [str(c.value) for s in book for row in s for c in row if c.value]
    assert any(
        "Самостоятельная работа" in text and "Преподаватель 1" in text for text in texts
    )


def test_incomplete_week_does_not_get_extra_invented_hours(state):
    week = regular_week(state)
    state.requirements["class"].hours = 30
    result = generate(state, week, ["g1"])
    assert result["status"] == "infeasible" and result["lessons"] == []
    assert "34 вместо 36" in result["message"]
    assert state.lessons == {}
    state.settings.target_exempt_weeks = [week]
    assert generate(state, week, ["g1"])["status"] in {"optimal", "feasible"}


def test_two_consecutive_weeks_close_period_hours_without_changing_first_week(state):
    week = regular_week(state)
    for req in list(state.requirements.values()):
        a = Allocation(
            id=f"a-{req.id}",
            subject_id=req.subject_id,
            group_ids=req.group_ids,
            teacher_ids=req.teacher_ids,
            kind=req.kind,
            hours=req.hours * 2,
            start_date=week,
            end_date=week + timedelta(days=13),
        )
        state.allocations[a.id] = a
        req.allocation_id = a.id
        second = req.model_copy(
            update={"id": f"next-{req.id}", "week": week + timedelta(days=7)}
        )
        state.requirements[second.id] = second
    for monday in [week, week + timedelta(days=7)]:
        first_week = {key: lesson.model_dump() for key, lesson in state.lessons.items()}
        result = generate(state, monday, ["g1"])
        assert result["status"] in {"optimal", "feasible"}, result
        state.lessons.update(
            {raw["id"]: Lesson.model_validate(raw) for raw in result["lessons"]}
        )
        assert all(
            state.lessons[key].model_dump() == raw for key, raw in first_week.items()
        )
        assert report(state, monday)["complete"]
    assert sum(l.hours for l in state.lessons.values()) == 72
    assert sum(l.hours for l in state.lessons.values() if l.kind == "self_study") == 8


def test_break_is_not_taught_time_and_one_hour_tail_starts_after_break(state):
    week = regular_week(state)
    choices = list(periods(state, week, 1))
    assert choices[:2] == [(510, 555), (560, 605)]
    invalid = Lesson(
        subject_id="s1",
        group_ids=["g1"],
        teacher_ids=["t1"],
        room_id="r1",
        day=week,
        start=555,
        end=600,
        hours=1,
    )
    state.lessons = {invalid.id: invalid}
    with pytest.raises(RuleError, match="без перемен"):
        validate(state)


def test_self_study_responsibility_does_not_imply_teacher_presence(state):
    week = regular_week(state)
    independent = Lesson(
        subject_id="s1",
        group_ids=["g1"],
        teacher_ids=["t1"],
        teacher_presence=False,
        kind="self_study",
        day=week,
        start=510,
        end=605,
        hours=2,
    )
    taught = Lesson(
        subject_id="s1",
        group_ids=["g2"],
        teacher_ids=["t1"],
        room_id="r1",
        day=week,
        start=510,
        end=605,
        hours=2,
    )
    state.lessons = {l.id: l for l in [independent, taught]}
    validate(state)
    independent.teacher_presence = True
    with pytest.raises(RuleError, match="Пересечение преподавателя"):
        validate(state)


def test_consultations_are_manual_and_count_toward_weekly_target(state):
    week = regular_week(state)
    state.requirements["class"].hours = 30
    manual = Requirement(
        id="consult",
        subject_id="s1",
        group_ids=["g1"],
        teacher_ids=["t1"],
        room_ids=["r1"],
        kind="consultation",
        week=week,
        hours=2,
    )
    state.requirements[manual.id] = manual
    assert generate(state, week, ["g1"])["status"] == "infeasible"
    existing = Lesson(
        requirement_id=manual.id,
        subject_id="s1",
        group_ids=["g1"],
        teacher_ids=["t1"],
        room_id="r1",
        kind="consultation",
        day=week,
        start=510,
        end=605,
        hours=2,
        locked=False,
    )
    state.lessons[existing.id] = existing
    result = generate(state, week, ["g1"])
    assert result["status"] in {"optimal", "feasible"}, result
    assert manual.id not in result["selected_requirement_ids"]
    assert all(l["kind"] != "consultation" for l in result["lessons"])
    state.lessons.update(
        {raw["id"]: Lesson.model_validate(raw) for raw in result["lessons"]}
    )
    assert report(state, week)["complete"]
    assert state.lessons[existing.id] == existing


def test_unattended_study_keeps_group_conflict_and_configured_room_conflict(state):
    week = regular_week(state)
    a = Lesson(
        subject_id="s1",
        group_ids=["g1"],
        teacher_ids=["t1"],
        room_id="r1",
        teacher_presence=False,
        kind="self_study",
        day=week,
        start=510,
        end=605,
        hours=2,
    )
    b = a.model_copy(
        update={"id": "second", "group_ids": ["g2"], "teacher_ids": ["t2"]}
    )
    state.lessons = {a.id: a, b.id: b}
    with pytest.raises(RuleError, match="Пересечение помещения"):
        validate(state)
    b.room_id = None
    b.group_ids = ["g1"]
    with pytest.raises(RuleError, match="Пересечение группы"):
        validate(state)


def test_kug_separate_groups_receive_full_hours_including_self_study(client):
    raw = client.get("/api/state").json()
    week = raw["state"]["requirements"]["n1"]["week"]
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
                "teacher_ids": ["t1"],
                "room_ids": ["r1"],
                "kind": "theory",
            },
            {
                "row_key": "5",
                "teacher_ids": ["t1"],
                "kind": "self_study",
                "teacher_presence": False,
            },
        ],
    }
    result = client.post(f"/api/imports/{doc}/kug", json={"version": 0, "item": item})
    assert result.status_code == 200, result.text
    imported = [
        r
        for r in client.get("/api/state").json()["state"]["requirements"].values()
        if r["source_ref"]
    ]
    assert len(imported) == 4
    assert sorted((r["group_ids"][0], r["kind"], r["hours"]) for r in imported) == [
        ("g1", "self_study", 2),
        ("g1", "theory", 4),
        ("g2", "self_study", 2),
        ("g2", "theory", 4),
    ]


def test_customer_confirmed_dash_is_joint_but_line_list_is_not():
    *_, assignments, pending, inherited = suggestions(
        "4\n1-9ЛД126 - 1-9ЛД226 Иванова А.Б."
    )
    assert assignments[0]["joint"] and not pending and not inherited
    *_, assignments, pending, inherited = suggestions(
        "4\n1-9ЛД126\n1-9ЛД226\nИванова А.Б."
    )
    assert not assignments[0]["joint"] and inherited


def test_manual_edit_is_locked_by_default_and_survives_generation(client):
    raw = client.get("/api/state").json()
    state = State.model_validate(raw["state"])
    week = state.requirements["n1"].week
    lesson = generate(state, week, [])["lessons"][0]
    lesson.pop("locked")
    lesson["note"] = "Ручная корректировка"
    saved = client.put(
        f"/api/lessons/{lesson['id']}", json={"version": 0, "item": lesson}
    )
    assert saved.status_code == 200, saved.text
    state = State.model_validate(client.get("/api/state").json()["state"])
    assert state.lessons[lesson["id"]].locked
    result = generate(state, week, [])
    assert result["status"] in {"optimal", "feasible"}
    assert all(l["id"] != lesson["id"] for l in result["lessons"])
    assert (
        sum(
            l["hours"]
            for l in result["lessons"]
            if l["requirement_id"] == lesson["requirement_id"]
        )
        == state.requirements[lesson["requirement_id"]].hours - lesson["hours"]
    )
