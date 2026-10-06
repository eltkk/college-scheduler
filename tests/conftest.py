"""Tests never connect to the deployment database."""

import os
import tempfile
from pathlib import Path

TEST_ROOT = Path(tempfile.mkdtemp(prefix="college-scheduler-tests-"))
url = os.getenv("TEST_DATABASE_URL", f"sqlite:///{TEST_ROOT}/test.sqlite")
if not url.startswith("sqlite:") and not url.endswith("/college_scheduler_test"):
    raise RuntimeError("Use a disposable database named college_scheduler_test")
os.environ.update(
    DATABASE_URL=url,
    SECURE_COOKIES="false",
    ALLOWED_HOSTS="testserver,localhost,127.0.0.1",
    DATA_DIR=str(TEST_ROOT / "uploads"),
    SOLVER_SECONDS="5",
)

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import delete
from app.auth import hasher
from app.db import Base, SessionLocal, User, Workspace, Audit, engine
from app.demo import demo_state
from app.main import app


def pytest_sessionstart(session):
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture
def state():
    return demo_state()


@pytest.fixture
def client(state):
    with SessionLocal() as db:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(delete(table))
        raw = state.model_dump(mode="json")
        db.add(Workspace(id=1, version=0, payload=raw))
        db.add(Audit(version=0, user_id="system", action="Test", snapshot=raw))
        password_hash = hasher.hash("test-only-password")
        for i in range(4):
            db.add(
                User(
                    id=f"u{i}",
                    login=f"editor{i+1}",
                    name=f"Редактор {i+1}",
                    password_hash=password_hash,
                )
            )
        db.commit()
    with TestClient(app) as c:
        result = c.post(
            "/api/auth/login",
            json={"login": "editor1", "password": "test-only-password"},
        )
        assert result.status_code == 200
        c.headers["X-CSRF-Token"] = result.json()["csrf"]
        yield c
