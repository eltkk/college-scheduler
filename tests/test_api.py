from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from io import BytesIO
import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from app.db import SessionLocal, Workspace, engine
from app.domain import Teacher
from app.main import app
from app.storage import StaleVersion, mutate
from app.worker import run_once
from test_imports import kug_file


def test_all_four_logins_have_equal_access(client):
    for i in range(1, 5):
        with TestClient(app) as c:
            r = c.post(
                "/api/auth/login",
                json={"login": f"editor{i}", "password": "test-only-password"},
            )
            assert r.status_code == 200
            c.headers["X-CSRF-Token"] = r.json()["csrf"]
            assert c.get("/api/state").status_code == 200
            version = c.get("/api/state").json()["version"]
            assert (
                c.put(
                    f"/api/catalog/subjects/extra{i}",
                    json={"version": version, "item": {"name": f"Subject {i}"}},
                ).status_code
                == 200
            )


def test_cookie_csrf_logout_and_auth_gate(client):
    assert "HttpOnly" in str(client.cookies) or client.cookies.get("scheduler_session")
    csrf = client.headers.pop("X-CSRF-Token")
    assert (
        client.put(
            "/api/catalog/teachers/new",
            json={"version": 0, "item": {"name": "Teacher"}},
        ).status_code
        == 403
    )
    client.headers["X-CSRF-Token"] = csrf
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/state").status_code == 401


def test_failed_logins_rate_limited(client):
    for i in range(10):
        assert (
            client.post(
                "/api/auth/login", json={"login": "nonexistent", "password": "bad"}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/auth/login", json={"login": "nonexistent", "password": "bad"}
        ).status_code
        == 429
    )


def test_stale_change_rejected_without_loss_and_history_restore(client):
    body = {"version": 0, "item": {"name": "New teacher"}}
    assert client.put("/api/catalog/teachers/new", json=body).status_code == 200
    assert client.put("/api/catalog/teachers/other", json=body).status_code == 409
    state = client.get("/api/state").json()
    assert (
        "new" in state["state"]["teachers"]
        and "other" not in state["state"]["teachers"]
    )
    assert client.post("/api/history/0/restore", json={"version": 1}).status_code == 200
    assert client.get("/api/state").json()["version"] == 2
    assert "new" not in client.get("/api/state").json()["state"]["teachers"]
    assert len(client.get("/api/history").json()) == 3


def test_deleting_used_resource_rolls_back(client):
    assert client.delete("/api/catalog/teachers/t1?version=0").status_code == 422
    assert client.get("/api/state").json()["version"] == 0
    assert "t1" in client.get("/api/state").json()["state"]["teachers"]


def test_async_generation_preview_apply_stale_and_reapply(client):
    week = client.get("/api/state").json()["state"]["requirements"]["n1"]["week"]
    r = client.post("/api/generations", json={"version": 0, "item": {"week": week}})
    assert r.status_code == 200
    job = r.json()["id"]
    assert client.get("/api/state").json()["state"]["lessons"] == {}
    assert run_once()
    assert client.get(f"/api/generations/{job}").json()["status"] == "completed"
    assert (
        client.post(f"/api/generations/{job}/apply", json={"version": 0}).status_code
        == 200
    )
    assert client.get("/api/check").json()["complete"]
    assert (
        client.post(f"/api/generations/{job}/apply", json={"version": 1}).status_code
        == 422
    )
    next_job = client.post(
        "/api/generations", json={"version": 1, "item": {"week": week}}
    ).json()["id"]
    run_once()
    assert (
        client.put(
            "/api/catalog/subjects/extra",
            json={"version": 1, "item": {"name": "Unrelated edit"}},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/generations/{next_job}/apply", json={"version": 2}
        ).status_code
        == 409
    )


def test_malformed_week_is_a_validation_error(client):
    assert (
        client.post(
            "/api/generations", json={"version": 0, "item": {"week": "wrong"}}
        ).status_code
        == 422
    )


def test_kug_preview_duplicate_confirm_and_no_silent_hour_loss(client):
    raw = kug_file()
    a = client.post("/api/imports?kind=kug", files={"file": ("test.xlsx", raw)})
    assert a.status_code == 200
    doc = a.json()["id"]
    b = client.post("/api/imports?kind=kug", files={"file": ("test.xlsx", raw)})
    assert b.json()["duplicate"] and b.json()["id"] == doc
    week = client.get("/api/state").json()["state"]["requirements"]["n1"]["week"]
    item = {
        "acknowledged": True,
        "sheet_key": "0",
        "week_key": "C:D",
        "week": week,
        "group_ids": ["g1"],
        "rows": [
            {
                "row_key": "4",
                "teacher_ids": ["t1"],
                "room_ids": ["r1"],
                "kind": "theory",
            }
        ],
    }
    assert (
        client.post(
            f"/api/imports/{doc}/kug", json={"version": 0, "item": item}
        ).status_code
        == 200
    )
    state = client.get("/api/state").json()["state"]
    imported = [r for r in state["requirements"].values() if r["source_ref"]]
    assert len(imported) == 1 and imported[0]["hours"] == 4
    assert len(next(iter(state["plans"].values()))["rows"]) == 2
    assert (
        client.post(
            f"/api/imports/{doc}/kug", json={"version": 1, "item": item}
        ).status_code
        == 422
    )
    bad = client.post(
        "/api/imports?kind=kug", files={"file": ("bad.xlsx", kug_file("=1+1"))}
    ).json()["id"]
    assert (
        client.post(
            f"/api/imports/{bad}/kug", json={"version": 1, "item": item}
        ).status_code
        == 422
    )


def test_swap_validates_final_times_atomically(client):
    state = client.get("/api/state").json()["state"]
    week = state["requirements"]["n1"]["week"]
    lesson = {
        "subject_id": "s1",
        "group_ids": ["g1"],
        "teacher_ids": ["t1"],
        "room_id": "r1",
        "day": week,
        "start": 510,
        "end": 600,
        "hours": 2,
    }
    assert (
        client.put("/api/lessons/a", json={"version": 0, "item": lesson}).status_code
        == 200
    )
    lesson.update(start=830, end=920)
    assert (
        client.put("/api/lessons/b", json={"version": 1, "item": lesson}).status_code
        == 200
    )
    assert (
        client.post(
            "/api/lessons/swap",
            json={"version": 2, "item": {"first": "a", "second": "b"}},
        ).status_code
        == 200
    )
    assert client.get("/api/state").json()["state"]["lessons"]["a"]["start"] == 830


def test_workload_mismatch_is_atomic(client):
    week = client.get("/api/state").json()["state"]["requirements"]["n1"]["week"]
    book = Workbook()
    s = book.active
    s.append(["группа", "предмет", "преподаватель", "кабинет", "часы"])
    s.append(["Группа 1;Группа 2", "Анатомия", "Преподаватель 1", "Аудитория 101", 5])
    buf = BytesIO()
    book.save(buf)
    doc = client.post(
        "/api/imports?kind=load", files={"file": ("load.xlsx", buf.getvalue())}
    ).json()["id"]
    r = client.post(
        f"/api/imports/{doc}/load",
        json={
            "version": 0,
            "item": {
                "week": week,
                "mapping": {
                    "group": "0",
                    "subject": "1",
                    "teacher": "2",
                    "room": "3",
                    "hours": "4",
                },
            },
        },
    )
    assert r.status_code == 422 and "отличаются" in r.text
    assert client.get("/api/state").json()["version"] == 0


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="Requires actual PostgreSQL row locks; CI runs this test",
)
def test_simultaneous_editors_cannot_commit_same_revision(client):
    barrier = Barrier(2)

    def edit(i):
        with SessionLocal() as db:
            barrier.wait(timeout=10)
            try:
                mutate(
                    db,
                    0,
                    f"u{i}",
                    "Concurrent edit",
                    lambda s: s.teachers.__setitem__(
                        f"new{i}", Teacher(id=f"new{i}", name=f"Teacher {i}")
                    ),
                )
                return "committed"
            except StaleVersion:
                return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, [0, 1]))
    assert sorted(results) == ["committed", "stale"]
    with SessionLocal() as db:
        row = db.get(Workspace, 1)
        assert row.version == 1
        assert sum(k.startswith("new") for k in row.payload["teachers"]) == 1


def test_history_retention_keeps_current_and_does_not_change_live_data(
    client, monkeypatch
):
    from app.config import settings
    from app.db import Audit
    from sqlalchemy import select

    monkeypatch.setattr(settings, "history_versions", 20)
    with SessionLocal() as db:
        raw = db.get(Workspace, 1).payload
        for version in range(1, 20):
            db.add(
                Audit(
                    version=version,
                    user_id="system",
                    action="Old test version",
                    snapshot=raw,
                )
            )
        db.get(Workspace, 1).version = 19
        db.commit()
    assert (
        client.put(
            "/api/catalog/teachers/extra",
            json={"version": 19, "item": {"name": "Teacher"}},
        ).status_code
        == 200
    )
    history = client.get("/api/history").json()
    assert (
        len(history) == 20
        and history[0]["version"] == 20
        and history[-1]["version"] == 1
    )
    assert (
        client.post("/api/history/0/restore", json={"version": 20}).status_code == 404
    )
    assert "extra" in client.get("/api/state").json()["state"]["teachers"]
