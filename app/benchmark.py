"""Repeatable anonymous performance sample; no database writes."""

import json
import time
from datetime import date, timedelta
from .domain import (
    CollegeSettings,
    Group,
    Lesson,
    Requirement,
    Room,
    State,
    Subject,
    Teacher,
)
from .scheduler import generate
from .validation import report


def main():
    state = State(settings=CollegeSettings(confirmed=True))
    week = date.today() - timedelta(days=date.today().weekday())
    state.groups = {
        str(i): Group(id=str(i), name=f"Group {i}", student_count=25) for i in range(20)
    }
    state.teachers = {
        str(i): Teacher(
            id=str(i), name=f"Teacher {i}", max_day_hours=8, max_week_hours=30
        )
        for i in range(40)
    }
    state.rooms = {
        str(i): Room(id=str(i), name=f"Room {i}", student_capacity=30)
        for i in range(20)
    }
    state.subjects = {str(i): Subject(id=str(i), name=f"Subject {i}") for i in range(5)}
    for group in range(20):
        for subject in range(5):
            req = Requirement(
                subject_id=str(subject),
                group_ids=[str(group)],
                teacher_ids=[str((group * 5 + subject) % 40)],
                room_ids=[str(group)],
                week=week,
                hours=6,
            )
            state.requirements[req.id] = req
    started = time.monotonic()
    result = generate(state, week, [])
    state.lessons = {raw["id"]: Lesson.model_validate(raw) for raw in result["lessons"]}
    print(
        json.dumps(
            {
                "groups": 20,
                "teachers": 40,
                "requirements": 100,
                "hours": 600,
                "lessons": len(state.lessons),
                "status": result["status"],
                "seconds": round(time.monotonic() - started, 2),
                "complete": report(state)["complete"],
            }
        )
    )


if __name__ == "__main__":
    main()
