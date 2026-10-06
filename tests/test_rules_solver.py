from datetime import timedelta
from io import BytesIO
import pytest
from openpyxl import load_workbook
from app.domain import Bell, Group, Lesson, Requirement, Room, Teacher, Window
from app.export import export_schedule
from app.scheduler import generate
from app.validation import RuleError, report, validate


def make_lesson(state, **changes):
    req = state.requirements["n1"]
    return Lesson(
        id="l1",
        requirement_id=req.id,
        subject_id=req.subject_id,
        group_ids=req.group_ids,
        teacher_ids=["t1"],
        room_id="r1",
        day=req.week,
        start=510,
        end=600,
        hours=2,
        **changes,
    )


def apply(state, result):
    state.lessons = {l["id"]: Lesson.model_validate(l) for l in result["lessons"]}
    return state


def test_generation_closes_exact_hours_including_shared_stream_and_odd_tail(state):
    result = generate(state, state.requirements["n1"].week, [])
    assert result["status"] in {"optimal", "feasible"}
    apply(state, result)
    assert report(state)["complete"]
    assert sum(l.hours for l in state.lessons.values() if l.requirement_id == "n1") == 4
    assert all(
        l.group_ids == ["g1", "g2"]
        for l in state.lessons.values()
        if l.requirement_id == "n1"
    )
    assert sum(l.hours for l in state.lessons.values() if l.requirement_id == "n4") == 3
    assert any(l.hours == 4 for l in state.lessons.values())


@pytest.mark.parametrize("resource", ["teacher", "group", "room"])
def test_conflicts_rejected(state, resource):
    a = make_lesson(state)
    b = Lesson(
        id="l2",
        subject_id="s2",
        group_ids=["g2" if resource != "group" else "g1"],
        teacher_ids=["t2" if resource != "teacher" else "t1"],
        room_id="r2" if resource != "room" else "r1",
        day=a.day,
        start=510,
        end=600,
        hours=2,
    )
    if resource != "group":
        a.group_ids = ["g1"]
        a.requirement_id = None
    state.lessons = {a.id: a, b.id: b}
    with pytest.raises(RuleError, match="Пересечение"):
        validate(state)


def test_parallel_sibling_practice_does_not_double_parent_student_hours(state):
    state.groups = {
        "p": Group(id="p", name="Whole", max_day_hours=2),
        "a": Group(id="a", name="A", parent_id="p", student_count=10),
        "b": Group(id="b", name="B", parent_id="p", student_count=10),
    }
    state.requirements = {}
    state.lessons = {
        g: Lesson(
            id=g,
            subject_id="s1",
            group_ids=[g],
            teacher_ids=[t],
            room_id=r,
            day=make_lesson_week(state),
            start=510,
            end=600,
            hours=2,
        )
        for g, t, r in [("a", "t1", "r1"), ("b", "t2", "r2")]
    }
    validate(state)
    state.lessons["whole"] = Lesson(
        id="whole",
        subject_id="s1",
        group_ids=["p"],
        teacher_ids=["t1"],
        room_id="r1",
        day=make_lesson_week(state),
        start=610,
        end=700,
        hours=2,
    )
    with pytest.raises(RuleError, match="предел"):
        validate(state)


def make_lesson_week(state):
    from datetime import date

    return date.today() - timedelta(days=date.today().weekday())


def test_two_one_hour_needs_fit_in_one_pair(state):
    week = state.requirements["n1"].week
    state.settings.bells = [Bell(number=1, start=510, end=600, hours=2)]
    state.settings.study_days = [0]
    state.requirements = {
        str(i): Requirement(
            id=str(i),
            subject_id=s,
            group_ids=["g1"],
            teacher_ids=["t1"],
            room_ids=["r1"],
            week=week,
            hours=1,
            block_hours=1,
        )
        for i, s in enumerate(["s1", "s2"])
    }
    result = generate(state, week, [])
    assert result["status"] == "optimal"
    assert sorted((l["start"], l["end"]) for l in result["lessons"]) == [
        (510, 555),
        (555, 600),
    ]


@pytest.mark.parametrize("capacity,status", [(30, "infeasible"), (40, "optimal")])
def test_room_cumulative_student_capacity(state, capacity, status):
    week = state.requirements["n1"].week
    state.settings.bells = [Bell(number=1, start=510, end=600, hours=2)]
    state.settings.study_days = [0]
    state.rooms["r1"].parallel_capacity = 2
    state.rooms["r1"].student_capacity = capacity
    state.requirements = {
        str(i): Requirement(
            id=str(i),
            subject_id="s1",
            group_ids=[g],
            teacher_ids=[t],
            room_ids=["r1"],
            week=week,
            hours=2,
        )
        for i, (g, t) in enumerate([("g1", "t1"), ("g2", "t2")])
    }
    result = generate(state, week, [])
    assert result["status"] == status
    if status == "optimal":
        validate(apply(state, result))


def test_locked_lesson_survives_regeneration(state):
    fixed = make_lesson(state, locked=True)
    state.lessons = {fixed.id: fixed}
    result = generate(state, fixed.day, [])
    assert result["status"] in {"optimal", "feasible"}
    additions = {l["id"]: Lesson.model_validate(l) for l in result["lessons"]}
    state.lessons.update(additions)
    assert state.lessons["l1"] == fixed
    assert report(state)["complete"]


def test_unavailability_and_holidays_are_enforced(state):
    week = state.requirements["n1"].week
    state.teachers["t1"].windows = [Window(weekday=0, start=510, end=600)]
    state.settings.holidays = [week]
    result = generate(state, week, [])
    assert result["status"] == "infeasible" and not result["lessons"]


def test_generation_requires_confirmed_calendar(state):
    state.settings.confirmed = False
    with pytest.raises(RuleError, match="Подтвердите"):
        generate(state, state.requirements["n1"].week, [])


def test_resource_delete_and_cyclic_group_links_rejected(state):
    del state.teachers["t1"]
    with pytest.raises(RuleError):
        validate(state)
    state.teachers["t1"] = Teacher(id="t1", name="Teacher")
    state.groups["g1"].parent_id = "g2"
    state.groups["g2"].parent_id = "g1"
    with pytest.raises(RuleError, match="Циклическая"):
        validate(state)


def test_transition_time_rejected(state):
    week = state.requirements["n1"].week
    state.settings.transition_minutes = 30
    state.rooms["r1"].building = "A"
    state.rooms["r2"].building = "B"
    a = make_lesson(state)
    a.requirement_id = None
    a.group_ids = ["g1"]
    b = Lesson(
        id="l2",
        subject_id="s2",
        group_ids=["g1"],
        teacher_ids=["t2"],
        room_id="r2",
        day=week,
        start=610,
        end=700,
        hours=2,
    )
    state.lessons = {a.id: a, b.id: b}
    with pytest.raises(RuleError, match="перехода"):
        validate(state)


def test_excel_preserves_shared_merges_hours_and_text_safety(state):
    week = state.requirements["n1"].week
    state.lessons = {"l1": make_lesson(state)}
    state.subjects["s1"].name = "=DANGEROUS()"
    book = load_workbook(BytesIO(export_schedule(state, week)))
    assert any(str(r) == "C4:D4" for r in book.worksheets[0].merged_cells.ranges)
    assert book.worksheets[0]["C4"].value.startswith("'=DANGEROUS()")
    assert book.worksheets[0]["C4"].data_type != "f"
    assert book["Часы"]["E2"].value == 2
    assert book["Часы"]["F2"].value == 2


def test_break_time_cannot_count_as_academic_hours(state):
    state.settings.bells = [
        Bell(number=1, start=510, end=600, hours=2),
        Bell(number=2, start=1200, end=1290, hours=2),
    ]
    lesson = make_lesson(state)
    lesson = Lesson.model_validate({**lesson.model_dump(), "start": 599, "end": 1201})
    state.lessons = {lesson.id: lesson}
    with pytest.raises(RuleError, match="без перемен"):
        validate(state)


def test_normal_two_hour_blocks_start_at_bells(state):
    from app.scheduler import periods

    assert {start for start, _ in periods(state, make_lesson_week(state), 2)} <= {
        b.start for b in state.settings.bells
    }


def test_known_students_exceeding_capacity_are_rejected_even_with_unknown_group(state):
    state.groups["g2"].student_count = None
    state.rooms["r1"].student_capacity = 10
    lesson = make_lesson(state)
    state.lessons = {lesson.id: lesson}
    with pytest.raises(RuleError, match="не вмещает"):
        validate(state)
