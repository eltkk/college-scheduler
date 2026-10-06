from collections import defaultdict
from datetime import timedelta
from .domain import State, Lesson


class RuleError(ValueError):
    def __init__(self, messages):
        self.messages = messages if isinstance(messages, list) else [messages]
        super().__init__("; ".join(self.messages))


def leaf_groups(state: State, ids: list[str]) -> set[str]:
    def descend(gid, path):
        if gid not in state.groups:
            raise RuleError("Группа не найдена")
        if gid in path:
            raise RuleError("Циклическая связь групп")
        children = [g.id for g in state.groups.values() if g.parent_id == gid]
        return (
            set().union(*(descend(x, path | {gid}) for x in children))
            if children
            else {gid}
        )

    return set().union(*(descend(gid, set()) for gid in ids))


def group_family(state: State, ids: list[str]) -> set[str]:
    result = set(ids)
    for gid in list(ids):
        parent = state.groups[gid].parent_id
        while parent:
            if parent in result:
                break
            result.add(parent)
            parent = state.groups[parent].parent_id
    return result


def available(resource, day, start, end):
    if day in resource.blocked_dates:
        return False
    if not resource.windows:
        return True
    dated = [x for x in resource.windows if x.day == day]
    windows = dated or [
        x for x in resource.windows if x.day is None and x.weekday == day.weekday()
    ]
    return any(x.start <= start and x.end >= end for x in windows)


def overlap(a: Lesson, b: Lesson):
    return a.day == b.day and a.start < b.end and b.start < a.end


def valid_references(state: State):
    for name in ["teachers", "groups", "rooms", "subjects", "requirements", "lessons"]:
        for key, value in getattr(state, name).items():
            if key != value.id:
                raise RuleError("Идентификатор записи изменять нельзя")
    for group in state.groups.values():
        if group.parent_id and group.parent_id not in state.groups:
            raise RuleError(f"Для группы «{group.name}» не найдена родительская группа")
        leaf_groups(state, [group.id])
    for kind, entries in [
        ("нагрузке", state.requirements.values()),
        ("занятии", state.lessons.values()),
    ]:
        for item in entries:
            if item.subject_id not in state.subjects:
                raise RuleError(
                    f"Предмет в {kind} не найден или используется удалённая запись"
                )
            for field, catalog in [
                ("group_ids", state.groups),
                ("teacher_ids", state.teachers),
            ]:
                ids = getattr(item, field)
                if len(set(ids)) != len(ids) or any(x not in catalog for x in ids):
                    raise RuleError(
                        f"Неверные или повторяющиеся группы/преподаватели в {kind}"
                    )
            rooms = item.room_ids if kind == "нагрузке" else [item.room_id]
            if len(set(rooms)) != len(rooms) or any(
                x not in state.rooms for x in rooms
            ):
                raise RuleError(f"Помещение в {kind} не найдено")


def validate(state: State):
    valid_references(state)
    lessons = list(state.lessons.values())
    participants = {x.id: leaf_groups(state, x.group_ids) for x in lessons}
    used_hours = defaultdict(int)
    daily = defaultdict(int)
    weekly = defaultdict(int)
    for lesson in lessons:
        subject = state.subjects[lesson.subject_id].name
        if (
            lesson.day.weekday() not in state.settings.study_days
            or lesson.day in state.settings.holidays
        ):
            raise RuleError(f"«{subject}»: неучебный день {lesson.day}")
        if lesson.end - lesson.start < lesson.hours * state.settings.academic_minutes:
            raise RuleError(
                f"«{subject}»: длительность меньше {lesson.hours} академических часов"
            )
        taught_minutes = sum(
            min(
                max(0, min(lesson.end, b.end) - max(lesson.start, b.start)),
                b.hours * state.settings.academic_minutes,
            )
            for b in state.settings.bells
        )
        if taught_minutes < lesson.hours * state.settings.academic_minutes:
            raise RuleError(
                f"«{subject}»: указанное число часов не помещается в учебные интервалы без перемен"
            )
        if not any(
            b.start <= lesson.start < b.end for b in state.settings.bells
        ) or not any(b.start < lesson.end <= b.end for b in state.settings.bells):
            raise RuleError(f"«{subject}»: время вне расписания звонков")
        if lesson.requirement_id:
            req = state.requirements.get(lesson.requirement_id)
            if req is None:
                raise RuleError("Занятие ссылается на удалённую нагрузку")
            if (
                req.subject_id != lesson.subject_id
                or req.kind != lesson.kind
                or set(req.group_ids) != set(lesson.group_ids)
            ):
                raise RuleError(
                    "Предмет, вид и состав занятия должны соответствовать выбранной нагрузке"
                )
            if (
                not set(lesson.teacher_ids) <= set(req.teacher_ids)
                or lesson.room_id not in req.room_ids
            ):
                raise RuleError(
                    "Преподаватель или помещение не разрешены для этой нагрузки"
                )
            if not req.week <= lesson.day < req.week + timedelta(days=7):
                raise RuleError("Занятие находится вне недели своей нагрузки")
            used_hours[req.id] += lesson.hours
            if used_hours[req.id] > req.hours:
                raise RuleError(
                    f"«{subject}»: размещено больше часов, чем в нагрузке ({req.hours})"
                )
        families = group_family(state, lesson.group_ids) | group_family(
            state, list(participants[lesson.id])
        )
        resources = [("teacher", x, state.teachers[x]) for x in lesson.teacher_ids]
        resources += [("group", x, state.groups[x]) for x in families]
        resources.append(("room", lesson.room_id, state.rooms[lesson.room_id]))
        monday = lesson.day - timedelta(days=lesson.day.weekday())
        for kind, rid, resource in resources:
            if not available(resource, lesson.day, lesson.start, lesson.end):
                raise RuleError(
                    f"«{resource.name}» недоступен: {lesson.day}, {lesson.start//60:02}:{lesson.start%60:02}"
                )
            if kind == "teacher":
                daily[kind, rid, lesson.day] += lesson.hours
                weekly[kind, rid, monday] += lesson.hours
                if (
                    resource.max_day_hours
                    and daily[kind, rid, lesson.day] > resource.max_day_hours
                ):
                    raise RuleError(f"«{resource.name}»: превышен дневной предел часов")
                if (
                    resource.max_week_hours
                    and weekly[kind, rid, monday] > resource.max_week_hours
                ):
                    raise RuleError(
                        f"«{resource.name}»: превышен недельный предел часов"
                    )
        # A parent's limit applies to each student unit, not the sum of concurrent sibling practices.
        for gid in participants[lesson.id]:
            daily["leaf", gid, lesson.day] += lesson.hours
            weekly["leaf", gid, monday] += lesson.hours
            for ancestor in group_family(state, [gid]):
                group = state.groups[ancestor]
                if (
                    group.max_day_hours
                    and daily["leaf", gid, lesson.day] > group.max_day_hours
                ):
                    raise RuleError(f"«{group.name}»: превышен дневной предел часов")
                if (
                    group.max_week_hours
                    and weekly["leaf", gid, monday] > group.max_week_hours
                ):
                    raise RuleError(f"«{group.name}»: превышен недельный предел часов")
    by_day = defaultdict(list)
    for lesson in lessons:
        by_day[lesson.day].append(lesson)
    for day_lessons in by_day.values():
        for i, a in enumerate(day_lessons):
            for b in day_lessons[i + 1 :]:
                shared_teachers = set(a.teacher_ids) & set(b.teacher_ids)
                shared_groups = participants[a.id] & participants[b.id]
                if overlap(a, b):
                    if shared_teachers:
                        teacher = state.teachers[next(iter(shared_teachers))].name
                        raise RuleError(
                            f"Пересечение преподавателя «{teacher}»: {a.day}"
                        )
                    if shared_groups:
                        group = state.groups[next(iter(shared_groups))].name
                        raise RuleError(f"Пересечение группы «{group}»: {a.day}")
                elif a.day == b.day and (shared_teachers or shared_groups):
                    earlier, later = (a, b) if a.start <= b.start else (b, a)
                    buildings = (
                        state.rooms[a.room_id].building,
                        state.rooms[b.room_id].building,
                    )
                    if (
                        buildings[0]
                        and buildings[1]
                        and buildings[0] != buildings[1]
                        and later.start - earlier.end
                        < state.settings.transition_minutes
                    ):
                        raise RuleError(
                            "Недостаточно времени для перехода между корпусами"
                        )
    for room in state.rooms.values():
        room_lessons = [x for x in lessons if x.room_id == room.id]
        for a in room_lessons:
            concurrent = [
                b for b in room_lessons if b.day == a.day and b.start <= a.start < b.end
            ]
            if len(concurrent) > room.parallel_capacity:
                raise RuleError(f"Пересечение помещения «{room.name}»: {a.day}")
            leaves = set().union(*(participants[b.id] for b in concurrent))
            counts = [state.groups[g].student_count for g in leaves]
            if (
                room.student_capacity
                and sum(x for x in counts if x is not None) > room.student_capacity
            ):
                raise RuleError(f"Помещение «{room.name}» не вмещает участников")


def report(state: State, week=None):
    errors = []
    try:
        validate(state)
    except RuleError as exc:
        errors = exc.messages
    totals = defaultdict(int)
    for lesson in state.lessons.values():
        if lesson.requirement_id:
            totals[lesson.requirement_id] += lesson.hours
    rows = [
        {
            "id": r.id,
            "subject": state.subjects[r.subject_id].name,
            "hours": r.hours,
            "scheduled": totals[r.id],
            "remaining": r.hours - totals[r.id],
            "week": r.week.isoformat(),
        }
        for r in state.requirements.values()
        if week is None or r.week == week
    ]
    warnings = []
    if not state.settings.confirmed:
        warnings.append("Учебные дни и расписание звонков ещё не подтверждены")
    if any(
        not x.requirement_id
        for x in state.lessons.values()
        if week is None or week <= x.day < week + timedelta(days=7)
    ):
        warnings.append(
            "Есть занятия без связи с нагрузкой; они не закрывают плановые часы"
        )
    if any(r.student_capacity for r in state.rooms.values()) and any(
        g.student_count is None for g in state.groups.values()
    ):
        warnings.append(
            "Не у всех групп указана численность: проверка вместимости может быть неполной"
        )
    if not rows:
        warnings.append("Для выбранной недели нет подтверждённой нагрузки")
    return {
        "errors": errors,
        "warnings": warnings,
        "hours": rows,
        "complete": bool(rows)
        and not errors
        and not warnings
        and all(x["remaining"] == 0 for x in rows),
    }
