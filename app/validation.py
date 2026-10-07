from collections import defaultdict
from datetime import timedelta
from .domain import State, Lesson, bell_spans


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


def occupied_teachers(lesson):
    return lesson.teacher_ids if lesson.teacher_presence else []


def weekly_target(state, week):
    return (
        None
        if week in state.settings.target_exempt_weeks
        else state.settings.target_week_hours
    )


def valid_references(state: State):
    for name in [
        "teachers",
        "groups",
        "rooms",
        "subjects",
        "requirements",
        "allocations",
        "lessons",
    ]:
        for key, value in getattr(state, name).items():
            if key != value.id:
                raise RuleError("Идентификатор записи изменять нельзя")
    for group in state.groups.values():
        if group.parent_id and group.parent_id not in state.groups:
            raise RuleError(f"Для группы «{group.name}» не найдена родительская группа")
        leaf_groups(state, [group.id])
    for kind, entries in [
        ("нагрузке", state.requirements.values()),
        ("семестровой нагрузке", state.allocations.values()),
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
            rooms = (
                item.room_ids
                if kind == "нагрузке"
                else [item.room_id] if kind == "занятии" and item.room_id else []
            )
            if len(set(rooms)) != len(rooms) or any(
                x not in state.rooms for x in rooms
            ):
                raise RuleError(f"Помещение в {kind} не найдено")


def validate_allocations(state):
    ranges = defaultdict(list)
    for a in state.allocations.values():
        for g in leaf_groups(state, a.group_ids):
            ranges[a.subject_id, a.kind, g].append(a)
    for entries in ranges.values():
        ordered = sorted(entries, key=lambda a: a.start_date)
        for previous, current in zip(ordered, ordered[1:]):
            if current.start_date <= previous.end_date:
                raise RuleError(
                    "Пересекающиеся семестровые назначения одной дисциплины, вида и группы. Уточните раздел дисциплины или даты"
                )
    used = defaultdict(int)
    for req in state.requirements.values():
        if not req.allocation_id:
            continue
        a = state.allocations.get(req.allocation_id)
        if a is None:
            raise RuleError(
                "Недельная нагрузка ссылается на удалённую семестровую запись"
            )
        if (
            req.subject_id != a.subject_id
            or req.kind != a.kind
            or set(req.group_ids) != set(a.group_ids)
            or set(req.teacher_ids) != set(a.teacher_ids)
            or req.teacher_mode != a.teacher_mode
            or req.teacher_presence != a.teacher_presence
        ):
            raise RuleError(
                "Недельные назначения должны соответствовать семестровой нагрузке"
            )
        if not req.week <= a.end_date or req.week + timedelta(days=6) < a.start_date:
            raise RuleError("Неделя находится вне периода семестровой нагрузки")
        used[a.id] += req.hours
        if used[a.id] > a.hours:
            raise RuleError(
                f"«{state.subjects[a.subject_id].name}»: недельные часы превышают семестровые ({a.hours})"
            )


def validate(state: State):
    valid_references(state)
    validate_allocations(state)
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
            max(0, min(lesson.end, end) - max(lesson.start, start))
            for b in state.settings.bells
            for start, end in bell_spans(state.settings, b)
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
                or req.teacher_presence != lesson.teacher_presence
                or set(req.group_ids) != set(lesson.group_ids)
            ):
                raise RuleError(
                    "Предмет, вид и состав занятия должны соответствовать выбранной нагрузке"
                )
            if not set(lesson.teacher_ids) <= set(
                req.teacher_ids
            ) or lesson.room_id not in (req.room_ids or [None]):
                raise RuleError(
                    "Преподаватель или помещение не разрешены для этой нагрузки"
                )
            if req.teacher_mode == "together" and set(lesson.teacher_ids) != set(
                req.teacher_ids
            ):
                raise RuleError(
                    "На совместном занятии должны присутствовать все назначенные преподаватели"
                )
            if req.allocation_id:
                a = state.allocations[req.allocation_id]
                if not a.start_date <= lesson.day <= a.end_date:
                    raise RuleError("Занятие находится вне дат семестровой нагрузки")
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
        resources = [
            ("teacher", x, state.teachers[x]) for x in occupied_teachers(lesson)
        ]
        resources += [("group", x, state.groups[x]) for x in families]
        if lesson.room_id:
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
            if (
                state.settings.max_group_day_hours
                and daily["leaf", gid, lesson.day] > state.settings.max_group_day_hours
            ):
                raise RuleError(
                    f"«{state.groups[gid].name}»: превышен дневной предел колледжа"
                )
            if (
                state.settings.max_group_week_hours
                and weekly["leaf", gid, monday] > state.settings.max_group_week_hours
            ):
                raise RuleError(
                    f"«{state.groups[gid].name}»: превышен недельный предел колледжа"
                )
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
                shared_teachers = set(occupied_teachers(a)) & set(occupied_teachers(b))
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
                        state.rooms[a.room_id].building if a.room_id else "",
                        state.rooms[b.room_id].building if b.room_id else "",
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
    by_room_day = defaultdict(list)
    for lesson in lessons:
        if lesson.room_id:
            by_room_day[lesson.room_id, lesson.day].append(lesson)
    for (rid, day), room_lessons in by_room_day.items():
        room = state.rooms[rid]
        events = sorted(
            [(l.start, 1, l.id) for l in room_lessons]
            + [(l.end, 0, l.id) for l in room_lessons]
        )
        active = set()
        for _, begin, lid in events:
            if not begin:
                active.discard(lid)
                continue
            active.add(lid)
            if len(active) > room.parallel_capacity:
                raise RuleError(f"Пересечение помещения «{room.name}»: {day}")
            leaves = set().union(*(participants[k] for k in active))
            known = sum(state.groups[g].student_count or 0 for g in leaves)
            if room.student_capacity and known > room.student_capacity:
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
    if any(
        not r.allocation_id
        and any(
            a.subject_id == r.subject_id
            and a.kind == r.kind
            and a.start_date <= r.week + timedelta(days=6)
            and r.week <= a.end_date
            and leaf_groups(state, r.group_ids) & leaf_groups(state, a.group_ids)
            for a in state.allocations.values()
        )
        for r in state.requirements.values()
        if week is None or r.week == week
    ):
        warnings.append(
            "Есть недельные строки без связи с соответствующей семестровой нагрузкой. Свяжите их для контроля семестровых часов"
        )
    group_hours = []
    weeks = {r.week for r in state.requirements.values()}
    weeks.update(
        l.day - timedelta(days=l.day.weekday()) for l in state.lessons.values()
    )
    if week is not None:
        weeks = {week}
    for monday in sorted(weeks):
        planned = defaultdict(int)
        actual = defaultdict(int)
        for req in state.requirements.values():
            if req.week == monday:
                for gid in leaf_groups(state, req.group_ids):
                    planned[gid] += req.hours
        for lesson in state.lessons.values():
            if monday <= lesson.day < monday + timedelta(days=7):
                for gid in leaf_groups(state, lesson.group_ids):
                    actual[gid] += lesson.hours
        for gid in sorted(planned.keys() | actual.keys()):
            target = weekly_target(state, monday)
            group_hours.append(
                {
                    "group_id": gid,
                    "group": state.groups[gid].name,
                    "week": monday.isoformat(),
                    "planned": planned[gid],
                    "scheduled": actual[gid],
                    "target": target,
                }
            )
            if target and actual[gid] != target:
                warnings.append(
                    f"«{state.groups[gid].name}», {monday}: размещено {actual[gid]} ч., норматив {target} ч. с учётом самостоятельной работы"
                )
    if any(
        r.kind in state.settings.manual_kinds and totals[r.id] < r.hours
        for r in state.requirements.values()
        if week is None or r.week == week
    ):
        warnings.append(
            "Консультации и аттестацию разместите отдельно вручную: они не входят в автоматический расчёт"
        )
    return {
        "errors": errors,
        "warnings": warnings,
        "hours": rows,
        "group_hours": group_hours,
        "complete": bool(rows)
        and not errors
        and not warnings
        and all(x["remaining"] == 0 for x in rows),
    }
