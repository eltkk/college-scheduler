from collections import defaultdict
from datetime import date, timedelta
from ortools.sat.python import cp_model
from .config import settings
from .domain import Lesson, State
from .validation import (
    RuleError,
    available,
    leaf_groups,
    group_family,
    overlap,
    validate,
    occupied_teachers,
    weekly_target,
)


def periods(state, day, hours):
    bells = sorted(state.settings.bells, key=lambda x: x.start)
    for i, first in enumerate(bells):
        # One-hour tails can occupy either academic hour of a two-hour pair.
        for offset in range(first.hours if hours == 1 else 1):
            remaining = hours
            for j, last in enumerate(bells[i:], i):
                begin = last.start + (
                    offset * (state.settings.academic_minutes + last.break_minutes)
                    if j == i
                    else 0
                )
                capacity = last.hours - (offset if j == i else 0)
                consumed = min(remaining, capacity)
                remaining -= consumed
                if remaining == 0:
                    end = (
                        last.end
                        if consumed == capacity
                        else begin
                        + consumed * state.settings.academic_minutes
                        + (consumed - 1) * last.break_minutes
                    )
                    yield first.start + offset * (
                        state.settings.academic_minutes + first.break_minutes
                    ), end
                    break


def generate(state: State, week: date, group_ids: list[str]):
    validate(state)
    if not state.settings.confirmed:
        raise RuleError("Подтвердите учебные дни и расписание звонков")
    if week.weekday() != 0:
        raise RuleError("Выберите понедельник учебной недели")
    if any(x not in state.groups for x in group_ids):
        raise RuleError("Выбранная группа не найдена")
    selected = leaf_groups(state, group_ids) if group_ids else set(state.groups)
    reqs = [
        r
        for r in state.requirements.values()
        if r.week == week
        and r.kind not in state.settings.manual_kinds
        and (not group_ids or leaf_groups(state, r.group_ids) <= selected)
    ]
    if not reqs:
        raise RuleError("Для выбранных групп и недели нет подтверждённой нагрузки")
    selected_ids = {r.id for r in reqs}
    fixed = [
        l
        for l in state.lessons.values()
        if l.requirement_id not in selected_ids or l.locked
    ]
    target = weekly_target(state, week)
    if target:
        projected = defaultdict(int)
        for req in reqs:
            remaining = req.hours - sum(
                l.hours for l in fixed if l.requirement_id == req.id
            )
            for gid in leaf_groups(state, req.group_ids):
                projected[gid] += remaining
        for lesson in fixed:
            if week <= lesson.day < week + timedelta(days=7):
                for gid in leaf_groups(state, lesson.group_ids):
                    projected[gid] += lesson.hours
        target_groups = (
            leaf_groups(state, group_ids)
            if group_ids
            else set().union(*(leaf_groups(state, r.group_ids) for r in reqs))
        )
        wrong = [
            f"{state.groups[g].name}: {projected[g]} вместо {target} ч."
            for g in sorted(target_groups)
            if projected[g] != target
        ]
        if wrong:
            return {
                "status": "infeasible",
                "message": "Не соблюдён недельный норматив с учётом С/Р. Исправьте нагрузку или разместите ручные консультации/аттестацию: "
                + "; ".join(wrong),
                "lessons": [],
                "selected_requirement_ids": list(selected_ids),
            }
    variables = []
    chunks = []
    model = cp_model.CpModel()
    teacher_day = defaultdict(list)
    group_day = defaultdict(list)
    teacher_week = defaultdict(list)
    group_week = defaultdict(list)
    room_times = defaultdict(list)
    teacher_intervals = defaultdict(list)
    group_intervals = defaultdict(list)
    room_intervals = defaultdict(list)
    room_demands = defaultdict(list)
    fixed_hours = defaultdict(int)
    for lesson in fixed:
        fixed_hours[lesson.requirement_id] += lesson.hours
        if not week <= lesson.day < week + timedelta(days=7):
            continue
        start = (lesson.day - week).days * 1440 + lesson.start
        end = (lesson.day - week).days * 1440 + lesson.end
        interval = model.new_interval_var(start, end - start, end, f"fixed{lesson.id}")
        for teacher in occupied_teachers(lesson):
            teacher_intervals[teacher].append(interval)
        for gid in leaf_groups(state, lesson.group_ids):
            group_intervals[gid].append(interval)
        if lesson.room_id:
            room_intervals[lesson.room_id].append(interval)
        sizes = [
            state.groups[g].student_count for g in leaf_groups(state, lesson.group_ids)
        ]
        if lesson.room_id:
            room_demands[lesson.room_id].append(sum(x for x in sizes if x is not None))
    objective = []
    for req in reqs:
        previous_positions = {}
        remaining = req.hours - fixed_hours[req.id]
        if remaining < 0:
            raise RuleError("Закреплённые занятия превышают план часов")
        req_chunks = []
        while remaining:
            duration = min(req.block_hours, remaining)
            remaining -= duration
            choices = []
            for weekday in state.settings.study_days:
                day = week + timedelta(days=weekday)
                if day in state.settings.holidays:
                    continue
                if req.allocation_id:
                    allocation = state.allocations[req.allocation_id]
                    if not allocation.start_date <= day <= allocation.end_date:
                        continue
                for start, end in periods(state, day, duration):
                    teacher_sets = (
                        [req.teacher_ids]
                        if req.teacher_mode == "together"
                        else [[t] for t in req.teacher_ids]
                    )
                    for teachers in teacher_sets:
                        for room in req.room_ids or [None]:
                            candidate = Lesson(
                                requirement_id=req.id,
                                subject_id=req.subject_id,
                                group_ids=req.group_ids,
                                teacher_ids=teachers,
                                teacher_presence=req.teacher_presence,
                                room_id=room,
                                day=day,
                                start=start,
                                end=end,
                                hours=duration,
                                kind=req.kind,
                            )
                            participants = leaf_groups(state, req.group_ids)
                            groups = group_family(
                                state, list(participants)
                            ) | group_family(state, req.group_ids)
                            resources = (
                                [
                                    state.teachers[t]
                                    for t in occupied_teachers(candidate)
                                ]
                                + ([state.rooms[room]] if room else [])
                                + [state.groups[g] for g in groups]
                            )
                            if not all(
                                available(resource, day, start, end)
                                for resource in resources
                            ):
                                continue
                            sizes = [
                                state.groups[g].student_count for g in participants
                            ]
                            size = sum(x for x in sizes if x is not None)
                            if (
                                size is not None
                                and room is not None
                                and state.rooms[room].student_capacity
                                and size > state.rooms[room].student_capacity
                            ):
                                continue
                            if len(variables) > 50000:
                                raise RuleError(
                                    "Слишком много вариантов. Уточните разрешённые помещения/преподавателей или формируйте меньший состав"
                                )
                            variable = model.new_bool_var(f"x{len(variables)}")
                            variables.append((variable, candidate))
                            choices.append(variable)
                            objective.append(variable * (start // 10))
                            for teacher in occupied_teachers(candidate):
                                teacher_day[teacher, day].append(variable * duration)
                                teacher_week[teacher].append(variable * duration)
                            for gid in leaf_groups(state, req.group_ids):
                                group_day[gid, day].append(variable * duration)
                                group_week[gid].append(variable * duration)
                            room_times[room, day].append((variable, candidate))
                            absolute = weekday * 1440 + start
                            interval = model.new_optional_interval_var(
                                absolute,
                                end - start,
                                weekday * 1440 + end,
                                variable,
                                f"i{len(variables)}",
                            )
                            for teacher in occupied_teachers(candidate):
                                teacher_intervals[teacher].append(interval)
                            for gid in participants:
                                group_intervals[gid].append(interval)
                            if room:
                                room_intervals[room].append(interval)
                                room_demands[room].append(size)
            if not choices:
                return {
                    "status": "infeasible",
                    "message": f"Не найден допустимый интервал: {state.subjects[req.subject_id].name}, блок {duration} ч.",
                    "lessons": [],
                    "selected_requirement_ids": list(selected_ids),
                }
            model.add_exactly_one(choices)
            position = model.new_int_var(0, len(choices) - 1, f"position{len(chunks)}")
            model.add(position == sum(i * v for i, v in enumerate(choices)))
            if duration in previous_positions:
                model.add(position > previous_positions[duration])
            previous_positions[duration] = position
            req_chunks.append(choices)
            chunks.append(choices)
    for intervals in list(teacher_intervals.values()) + list(group_intervals.values()):
        model.add_no_overlap(intervals)
    for rid, intervals in room_intervals.items():
        room = state.rooms[rid]
        model.add_cumulative(intervals, [1] * len(intervals), room.parallel_capacity)
        if room.student_capacity and all(x is not None for x in room_demands[rid]):
            model.add_cumulative(intervals, room_demands[rid], room.student_capacity)
    if state.settings.transition_minutes:
        participant_cache = {
            l.id: leaf_groups(state, l.group_ids) for _, l in variables
        }
        candidates_by_resource = defaultdict(list)
        for v, l in variables:
            for key in [("teacher", x, l.day) for x in occupied_teachers(l)] + [
                ("group", x, l.day) for x in participant_cache[l.id]
            ]:
                candidates_by_resource[key].append((v, l))
        for key, choices in candidates_by_resource.items():
            relevant_fixed = [
                l
                for l in fixed
                if l.day == key[2]
                and (
                    key[1] in occupied_teachers(l)
                    if key[0] == "teacher"
                    else key[1] in leaf_groups(state, l.group_ids)
                )
            ]
            for i, (va, a) in enumerate(choices):
                for vb, b in choices[i + 1 :] + [(None, l) for l in relevant_fixed]:
                    buildings = (
                        state.rooms[a.room_id].building if a.room_id else "",
                        state.rooms[b.room_id].building if b.room_id else "",
                    )
                    if (
                        all(buildings)
                        and buildings[0] != buildings[1]
                        and not overlap(a, b)
                    ):
                        first, last = (a, b) if a.start <= b.start else (b, a)
                        if last.start - first.end < state.settings.transition_minutes:
                            (
                                model.add(va + vb <= 1)
                                if vb is not None
                                else model.add(va == 0)
                            )
    for (tid, day), terms in teacher_day.items():
        teacher = state.teachers[tid]
        external = sum(
            l.hours for l in fixed if tid in occupied_teachers(l) and l.day == day
        )
        if teacher.max_day_hours:
            model.add(sum(terms) + external <= teacher.max_day_hours)
    for tid, terms in teacher_week.items():
        teacher = state.teachers[tid]
        external = sum(
            l.hours
            for l in fixed
            if tid in occupied_teachers(l) and week <= l.day < week + timedelta(days=7)
        )
        if teacher.max_week_hours:
            model.add(sum(terms) + external <= teacher.max_week_hours)
    for (gid, day), terms in group_day.items():
        limits = [
            state.groups[x].max_day_hours
            for x in group_family(state, [gid])
            if state.groups[x].max_day_hours
        ]
        if state.settings.max_group_day_hours:
            limits.append(state.settings.max_group_day_hours)
        external = sum(
            l.hours
            for l in fixed
            if gid in leaf_groups(state, l.group_ids) and l.day == day
        )
        if limits:
            model.add(sum(terms) + external <= min(limits))
        if state.settings.preferred_day_hours:
            extra = model.new_int_var(0, 200, f"extra{gid}{day}")
            model.add_max_equality(
                extra, [0, sum(terms) + external - state.settings.preferred_day_hours]
            )
            objective.append(extra * 5000)
    for gid, terms in group_week.items():
        limits = [
            state.groups[x].max_week_hours
            for x in group_family(state, [gid])
            if state.groups[x].max_week_hours
        ]
        if state.settings.max_group_week_hours:
            limits.append(state.settings.max_group_week_hours)
        external = sum(
            l.hours
            for l in fixed
            if gid in leaf_groups(state, l.group_ids)
            and week <= l.day < week + timedelta(days=7)
        )
        if limits:
            model.add(sum(terms) + external <= min(limits))
    if state.settings.avoid_group_gaps:
        bell_choices = defaultdict(list)
        fixed_bells = set()
        bells = sorted(state.settings.bells, key=lambda b: b.start)
        for variable, candidate in variables:
            for gid in leaf_groups(state, candidate.group_ids):
                for index, bell in enumerate(bells):
                    if candidate.start < bell.end and bell.start < candidate.end:
                        bell_choices[gid, candidate.day, index].append(variable)
        for lesson in fixed:
            if week <= lesson.day < week + timedelta(days=7):
                for gid in leaf_groups(state, lesson.group_ids):
                    for index, bell in enumerate(bells):
                        if lesson.start < bell.end and bell.start < lesson.end:
                            fixed_bells.add((gid, lesson.day, index))
        for gid, day in group_day:
            present = []
            for index in range(len(bells)):
                key = (gid, day, index)
                flag = model.new_bool_var(f"bell{gid}{day}{index}")
                model.add_max_equality(
                    flag, [1] if key in fixed_bells else bell_choices[key] or [0]
                )
                present.append(flag)
            for index in range(1, len(bells) - 1):
                before = model.new_bool_var(f"before{gid}{day}{index}")
                after = model.new_bool_var(f"after{gid}{day}{index}")
                gap = model.new_bool_var(f"gap{gid}{day}{index}")
                model.add_max_equality(before, present[:index])
                model.add_max_equality(after, present[index + 1 :])
                model.add(gap >= before + after - present[index] - 1)
                objective.append(gap * 10000)
    model.minimize(sum(objective))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = settings.solver_seconds
    solver.parameters.num_search_workers = settings.solver_workers
    solver.parameters.random_seed = 1
    status = solver.solve(model)
    statuses = {
        cp_model.OPTIMAL: "optimal",
        cp_model.FEASIBLE: "feasible",
        cp_model.INFEASIBLE: "infeasible",
        cp_model.UNKNOWN: "timeout",
        cp_model.MODEL_INVALID: "invalid",
    }
    tag = statuses[status]
    messages = {
        "optimal": "Найдено расписание без обязательных нарушений",
        "feasible": "Найден допустимый вариант",
        "infeasible": "Ограничения несовместимы. Проверьте доступность, часы, помещения и закрепления",
        "timeout": "За отведённое время решение не найдено. Невозможность не доказана",
        "invalid": "Ошибка модели: проверьте исходные данные",
    }
    lessons = (
        [l for v, l in variables if solver.boolean_value(v)]
        if tag in {"optimal", "feasible"}
        else []
    )
    if lessons or tag in {"optimal", "feasible"}:
        check = state.model_copy(deep=True)
        check.lessons = {l.id: l for l in fixed + lessons}
        validate(check)
        for req in reqs:
            if (
                sum(
                    l.hours
                    for l in check.lessons.values()
                    if l.requirement_id == req.id
                )
                != req.hours
            ):
                raise RuleError("Независимая проверка обнаружила потерю часов")
    return {
        "status": tag,
        "message": messages[tag],
        "lessons": [l.model_dump(mode="json") for l in lessons],
        "selected_requirement_ids": list(selected_ids),
        "elapsed": solver.wall_time,
    }
