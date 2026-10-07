from datetime import date
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, model_validator


def uid() -> str:
    return uuid4().hex


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Window(Model):
    weekday: int = Field(ge=0, le=6)
    start: int = Field(ge=0, le=1439)
    end: int = Field(ge=1, le=1440)
    day: date | None = None

    @model_validator(mode="after")
    def interval(self):
        if self.start >= self.end:
            raise ValueError("Начало интервала должно быть раньше окончания")
        return self


class Named(Model):
    id: str = Field(default_factory=uid, min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=300)


class Teacher(Named):
    windows: list[Window] = Field(default_factory=list)
    blocked_dates: list[date] = Field(default_factory=list)
    max_day_hours: int | None = Field(default=None, ge=1, le=24)
    max_week_hours: int | None = Field(default=None, ge=1, le=168)


class Group(Named):
    program: str = ""
    stream: str = ""
    course: int = Field(default=1, ge=1, le=6)
    entry_year: int | None = Field(default=None, ge=2000, le=2100)
    base: Literal["9", "11"] = "9"
    parent_id: str | None = None
    student_count: int | None = Field(default=None, ge=1, le=500)
    windows: list[Window] = Field(default_factory=list)
    blocked_dates: list[date] = Field(default_factory=list)
    max_day_hours: int | None = Field(default=None, ge=1, le=24)
    max_week_hours: int | None = Field(default=None, ge=1, le=168)


class Room(Named):
    building: str = ""
    kind: Literal["classroom", "lab", "gym", "clinic"] = "classroom"
    parallel_capacity: int = Field(default=1, ge=1, le=50)
    student_capacity: int | None = Field(default=None, ge=1, le=2000)
    windows: list[Window] = Field(default_factory=list)
    blocked_dates: list[date] = Field(default_factory=list)


class Subject(Named):
    code: str = Field(default="", max_length=100)


LessonKind = Literal[
    "theory",
    "practice",
    "consultation",
    "assessment",
    "training",
    "coursework",
    "self_study",
]
TeacherMode = Literal["alternative", "together"]


class Teaching(Model):
    teacher_presence: bool = True

    @model_validator(mode="after")
    def attendance(self):
        if not self.teacher_presence and self.kind != "self_study":
            raise ValueError(
                "Отсутствие преподавателя допустимо только для самостоятельной работы"
            )
        return self


class Allocation(Teaching):
    """Confirmed period workload. It never becomes weekly hours by itself."""

    id: str = Field(default_factory=uid, min_length=1, max_length=64)
    subject_id: str
    group_ids: list[str] = Field(min_length=1)
    teacher_ids: list[str] = Field(min_length=1)
    teacher_mode: TeacherMode = "alternative"
    kind: LessonKind = "theory"
    hours: int = Field(ge=1, le=3000)
    start_date: date
    end_date: date
    period: str = Field(default="", max_length=300)
    source_ref: str = Field(default="", max_length=1000)
    note: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def dates(self):
        if (
            self.start_date > self.end_date
            or (self.end_date - self.start_date).days > 366
        ):
            raise ValueError("Период нагрузки должен быть от одного дня до года")
        return self


class Requirement(Teaching):
    id: str = Field(default_factory=uid, min_length=1, max_length=64)
    subject_id: str
    group_ids: list[str] = Field(min_length=1)
    teacher_ids: list[str] = Field(min_length=1)
    teacher_mode: TeacherMode = "alternative"
    allocation_id: str | None = None
    room_ids: list[str] = Field(default_factory=list)
    week: date
    kind: LessonKind = "theory"
    hours: int = Field(ge=1, le=200)
    block_hours: int = Field(default=2, ge=1, le=24)
    source_ref: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def monday(self):
        if self.week.weekday() != 0:
            raise ValueError("Неделя должна начинаться с понедельника")
        if not self.room_ids and self.kind != "self_study":
            raise ValueError("Укажите разрешённые помещения для занятия")
        return self


class Lesson(Teaching):
    id: str = Field(default_factory=uid, min_length=1, max_length=64)
    requirement_id: str | None = None
    subject_id: str
    group_ids: list[str] = Field(min_length=1)
    teacher_ids: list[str] = Field(min_length=1)
    room_id: str | None = None
    day: date
    start: int = Field(ge=0, le=1439)
    end: int = Field(ge=1, le=1440)
    hours: int = Field(ge=1, le=24)
    kind: LessonKind = "theory"
    locked: bool = False
    note: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def interval(self):
        if self.start >= self.end:
            raise ValueError("Начало занятия должно быть раньше окончания")
        if not self.room_id and self.kind != "self_study":
            raise ValueError("Укажите помещение для занятия")
        return self


class Bell(Model):
    number: int = Field(ge=1, le=20)
    start: int = Field(ge=0, le=1439)
    end: int = Field(ge=1, le=1440)
    hours: int = Field(default=2, ge=1, le=8)
    break_minutes: int = Field(default=0, ge=0, le=30)


def bell_spans(settings, bell):
    """Teaching minutes only; the internal break never closes plan hours."""
    for hour in range(bell.hours):
        start = bell.start + hour * (settings.academic_minutes + bell.break_minutes)
        yield start, start + settings.academic_minutes


class CollegeSettings(Model):
    name: str = "Расписание колледжа"
    confirmed: bool = False
    academic_minutes: int = Field(default=45, ge=20, le=90)
    study_days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    holidays: list[date] = Field(default_factory=list)
    bells: list[Bell] = Field(
        default_factory=lambda: [
            Bell(number=i + 1, start=s, end=s + 90)
            for i, s in enumerate([510, 610, 730, 830, 930])
        ]
    )
    transition_minutes: int = Field(default=0, ge=0, le=180)
    max_group_day_hours: int | None = Field(default=None, ge=1, le=24)
    max_group_week_hours: int | None = Field(default=None, ge=1, le=168)
    target_week_hours: int | None = Field(default=None, ge=1, le=168)
    target_exempt_weeks: list[date] = Field(default_factory=list)
    preferred_day_hours: int | None = Field(default=None, ge=1, le=24)
    avoid_group_gaps: bool = False
    manual_kinds: list[LessonKind] = Field(default_factory=list)

    @model_validator(mode="after")
    def calendar(self):
        if not self.study_days or len(set(self.study_days)) != len(self.study_days):
            raise ValueError("Укажите учебные дни без повторений")
        if any(x < 0 or x > 6 for x in self.study_days):
            raise ValueError("Неверный учебный день")
        if not self.bells or len({x.number for x in self.bells}) != len(self.bells):
            raise ValueError("Укажите пары с уникальными номерами")
        ordered = sorted(self.bells, key=lambda x: x.start)
        for i, bell in enumerate(ordered):
            if (
                bell.start >= bell.end
                or bell.end - bell.start
                < bell.hours * self.academic_minutes
                + (bell.hours - 1) * bell.break_minutes
            ):
                raise ValueError(
                    "Время пары меньше указанного числа академических часов"
                )
            if i and ordered[i - 1].end > bell.start:
                raise ValueError("Пары не должны пересекаться")
        if any(w.weekday() != 0 for w in self.target_exempt_weeks):
            raise ValueError(
                "Исключения недельного норматива задаются датами понедельников"
            )
        if len(set(self.manual_kinds)) != len(self.manual_kinds):
            raise ValueError("Виды ручного составления не должны повторяться")
        if (
            self.target_week_hours
            and self.max_group_week_hours
            and self.target_week_hours > self.max_group_week_hours
        ):
            raise ValueError("Недельный норматив превышает предельную нагрузку")
        return self


def college_profile():
    """Rules confirmed by the customer on 6-7 October 2026; applied explicitly."""
    return CollegeSettings(
        confirmed=False,
        academic_minutes=45,
        study_days=[0, 1, 2, 3, 4],
        bells=[
            Bell(number=i + 1, start=start, end=end, hours=2, break_minutes=5)
            for i, (start, end) in enumerate(
                [
                    (510, 605),
                    (635, 730),
                    (760, 855),
                    (885, 980),
                    (990, 1085),
                ]
            )
        ],
        max_group_day_hours=10,
        max_group_week_hours=36,
        target_week_hours=36,
        preferred_day_hours=8,
        avoid_group_gaps=True,
        manual_kinds=["consultation", "assessment"],
    )


class State(Model):
    schema_version: Literal[1] = 1
    settings: CollegeSettings = Field(default_factory=CollegeSettings)
    teachers: dict[str, Teacher] = Field(default_factory=dict)
    groups: dict[str, Group] = Field(default_factory=dict)
    rooms: dict[str, Room] = Field(default_factory=dict)
    subjects: dict[str, Subject] = Field(default_factory=dict)
    requirements: dict[str, Requirement] = Field(default_factory=dict)
    allocations: dict[str, Allocation] = Field(default_factory=dict)
    lessons: dict[str, Lesson] = Field(default_factory=dict)
    plans: dict[str, dict] = Field(default_factory=dict)


CATALOG_MODELS = {
    "teachers": Teacher,
    "groups": Group,
    "rooms": Room,
    "subjects": Subject,
}
KIND_LABELS = {
    "theory": "Теория",
    "practice": "Практика",
    "consultation": "Консультация",
    "assessment": "Аттестация",
    "training": "Практика УП/ПП",
    "coursework": "Курсовая работа",
    "self_study": "Самостоятельная работа",
}
