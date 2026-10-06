from datetime import date, timedelta
from .domain import CollegeSettings, Group, Requirement, Room, State, Subject, Teacher


def demo_state():
    state = State(settings=CollegeSettings(name="Учебный пример", confirmed=True))
    groups = [
        Group(
            id="g1",
            name="Группа 1",
            program="Учебная программа",
            stream="Поток 1",
            student_count=20,
        ),
        Group(
            id="g2",
            name="Группа 2",
            program="Учебная программа",
            stream="Поток 1",
            student_count=20,
        ),
    ]
    teachers = [
        Teacher(id="t1", name="Преподаватель 1", max_day_hours=8),
        Teacher(id="t2", name="Преподаватель 2", max_day_hours=8),
    ]
    rooms = [
        Room(id="r1", name="Аудитория 101", student_capacity=60),
        Room(id="r2", name="Практический кабинет", kind="lab", student_capacity=30),
    ]
    subjects = [
        Subject(id="s1", name="Анатомия", code="ОП.01"),
        Subject(id="s2", name="Иностранный язык", code="СГ.02"),
    ]
    for name, items in [
        ("groups", groups),
        ("teachers", teachers),
        ("rooms", rooms),
        ("subjects", subjects),
    ]:
        setattr(state, name, {item.id: item for item in items})
    week = date.today() - timedelta(days=date.today().weekday())
    needs = [
        Requirement(
            id="n1",
            subject_id="s1",
            group_ids=["g1", "g2"],
            teacher_ids=["t1"],
            room_ids=["r1"],
            week=week,
            hours=4,
        ),
        Requirement(
            id="n2",
            subject_id="s1",
            group_ids=["g1"],
            teacher_ids=["t1"],
            room_ids=["r2"],
            week=week,
            hours=4,
            kind="practice",
            block_hours=4,
        ),
        Requirement(
            id="n3",
            subject_id="s1",
            group_ids=["g2"],
            teacher_ids=["t2"],
            room_ids=["r2"],
            week=week,
            hours=4,
            kind="practice",
            block_hours=4,
        ),
        Requirement(
            id="n4",
            subject_id="s2",
            group_ids=["g1"],
            teacher_ids=["t2"],
            room_ids=["r1", "r2"],
            week=week,
            hours=3,
            kind="practice",
        ),
    ]
    state.requirements = {x.id: x for x in needs}
    return state
