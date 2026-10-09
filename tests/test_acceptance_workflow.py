"""Anonymous regression cases for the confirmed college scheduling workflow."""
from datetime import date, timedelta
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.domain import Allocation, Group, Lesson, Requirement, Room, Teacher, Window, college_profile
from app.main import app
from app.worker import run_once


@pytest.fixture
def state(state):
    state.settings = college_profile()
    state.settings.confirmed = True
    state.groups['g3'] = Group(id='g3', name='Внешняя группа', student_count=20)
    state.teachers['t3'] = Teacher(id='t3', name='Другой преподаватель')
    state.rooms['r3'] = Room(id='r3', name='Другой кабинет')
    state.teachers['t1'].windows = [
        Window(weekday=day, start=bell.start, end=bell.end)
        for day in state.settings.study_days for bell in state.settings.bells
        if (day, bell.number) not in {(0, 1), (3, 2), (4, 1)}
    ]
    state.requirements = {}
    state.allocations = {}
    state.lessons = {}
    for index, kind in enumerate(('theory', 'practice')):
        week = date(2026, 10, 12) + timedelta(days=7 * index)
        allocation = Allocation(id=f'a-{index}', subject_id='s1', group_ids=['g1', 'g2'],
            teacher_ids=['t1'], kind=kind, hours=34, start_date=week, end_date=week+timedelta(days=6))
        state.allocations[allocation.id] = allocation
        req = Requirement(id=f'class-{index}', subject_id='s1', group_ids=['g1', 'g2'],
            teacher_ids=['t1'], room_ids=['r1'], week=week, kind=kind, hours=34,
            allocation_id=allocation.id)
        study = Requirement(id=f'study-{index}', subject_id='s2', group_ids=['g1', 'g2'],
            teacher_ids=['t2'], week=week, kind='self_study', hours=2, teacher_presence=False)
        state.requirements[req.id] = req
        state.requirements[study.id] = study
        bell = state.settings.bells[1]
        lesson = Lesson(id=f'pin-{index}', requirement_id=req.id, subject_id=req.subject_id,
            group_ids=req.group_ids, teacher_ids=req.teacher_ids, room_id='r1',
            day=week+timedelta(days=1), start=bell.start, end=bell.end, hours=2,
            kind=kind, locked=True, note='Повторяется день и пара, вид занятия по плану этой недели')
        state.lessons[lesson.id] = lesson
    return state


def calculate(client, week):
    before = client.get('/api/state').json()
    created = client.post('/api/generations', json={
        'version': before['version'], 'item': {'week': week, 'group_ids': ['g1', 'g2']}})
    assert created.status_code == 200, created.text
    job = created.json()['id']
    assert run_once()
    result = client.get(f'/api/generations/{job}').json()
    assert result['status'] == 'completed', result
    applied = client.post(f'/api/generations/{job}/apply', json={'version': before['version']})
    assert applied.status_code == 200, applied.text
    return client.get('/api/state').json()


def test_two_week_api_generation_export_and_four_editors_preserve_fixed_slots(client):
    original = client.get('/api/state').json()['state']
    pins = original['lessons']
    first = calculate(client, '2026-10-12')
    after_first = first['state']['lessons']
    both = calculate(client, '2026-10-19')
    assert all(both['state']['lessons'][key] == raw for key, raw in after_first.items())
    for index in range(1, 5):
        with TestClient(app) as editor:
            auth = editor.post('/api/auth/login', json={'login': f'editor{index}', 'password': 'test-only-password'})
            assert auth.status_code == 200
            editor.headers['X-CSRF-Token'] = auth.json()['csrf']
            snapshot = editor.get('/api/state').json()
            lesson = {**snapshot['state']['lessons']['pin-0'], 'note': f'Правка редактора {index}'}
            saved = editor.put('/api/lessons/pin-0', json={'version': snapshot['version'], 'item': lesson})
            assert saved.status_code == 200, saved.text
            assert client.get('/api/state').json()['state']['lessons']['pin-0']['note'] == lesson['note']
    final = calculate(client, '2026-10-12')['state']
    assert final['lessons']['pin-0']['note'] == 'Правка редактора 4'
    for key, raw in pins.items():
        assert all(final['lessons'][key][field] == raw[field]
                   for field in ('day', 'start', 'end', 'group_ids', 'teacher_ids', 'kind', 'locked'))
    for week in ('2026-10-12', '2026-10-19'):
        check = client.get(f'/api/check?week={week}').json()
        assert check['complete'], check
        assert len(check['group_hours']) == 2
        assert all(row['planned'] == row['scheduled'] == row['target'] == 36 for row in check['group_hours'])
        exported = client.get(f'/api/export.xlsx?week={week}')
        assert exported.status_code == 200
        rows = list(load_workbook(BytesIO(exported.content), data_only=True)['Часы'].iter_rows(min_row=2, values_only=True))
        assert len(rows) == 2 and sorted(row[3] for row in rows) == [2, 34]
        assert all(row[3] == row[4] and row[5] == 0 for row in rows)


@pytest.mark.parametrize('resource', ['teacher', 'group', 'room'])
def test_resource_collision_is_atomic(client, resource):
    before = client.get('/api/state').json()
    fixed = before['state']['lessons']['pin-0']
    lesson = {**fixed, 'id': 'conflicting', 'requirement_id': None,
              'group_ids': ['g3'], 'teacher_ids': ['t3'], 'room_id': 'r3'}
    if resource == 'teacher':
        lesson['teacher_ids'] = ['t1']
    elif resource == 'group':
        lesson['group_ids'] = ['g1']
    else:
        lesson['room_id'] = 'r1'
    rejected = client.put('/api/lessons/conflicting', json={'version': before['version'], 'item': lesson})
    assert rejected.status_code == 422, rejected.text
    assert client.get('/api/state').json() == before


def test_red_sd_manual_move_is_rejected_without_changing_original(client):
    before = client.get('/api/state').json()
    fixed = before['state']['lessons']['pin-0']
    bell = before['state']['settings']['bells'][0]
    moved = {**fixed, 'day': '2026-10-12', 'start': bell['start'], 'end': bell['end']}
    rejected = client.put('/api/lessons/pin-0', json={'version': before['version'], 'item': moved})
    assert rejected.status_code == 422 and 'недоступен' in rejected.text
    assert client.get('/api/state').json() == before


def test_group_rename_keeps_stream_membership_links_and_export(client):
    generated = calculate(client, '2026-10-12')
    group = {**generated['state']['groups']['g2'], 'name': 'Подтверждённое название группы 6', 'stream': '3'}
    saved = client.put('/api/catalog/groups/g2', json={'version': generated['version'], 'item': group})
    assert saved.status_code == 200, saved.text
    after = client.get('/api/state').json()['state']
    assert after['lessons'] == generated['state']['lessons']
    assert after['requirements'] == generated['state']['requirements']
    assert after['groups']['g2']['stream'] == '3'
    response = client.get('/api/export.xlsx?week=2026-10-12')
    texts = [str(c.value) for sheet in load_workbook(BytesIO(response.content)) for row in sheet for c in row if c.value]
    assert any(group['name'] in text for text in texts)


def test_generation_candidate_cannot_overwrite_later_manual_edit(client):
    initial = client.get('/api/state').json()
    queued = client.post('/api/generations', json={'version': initial['version'], 'item': {'week': '2026-10-12'}})
    assert queued.status_code == 200
    job = queued.json()['id']
    changed = {**initial['state']['lessons']['pin-0'], 'note': 'Не перезаписывать свежую правку'}
    assert client.put('/api/lessons/pin-0', json={'version': initial['version'], 'item': changed}).status_code == 200
    assert run_once()
    current = client.get('/api/state').json()
    rejected = client.post(f'/api/generations/{job}/apply', json={'version': current['version']})
    assert rejected.status_code == 409, rejected.text
    assert client.get('/api/state').json() == current
