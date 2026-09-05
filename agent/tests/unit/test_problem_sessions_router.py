from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.problems.domain.models import Problem, ProblemStatus
from app.problems.infrastructure.sqlite_repository import SqliteProblemRepository
from app.shared.config import get_settings
from app.shared.database import run_migrations
from app.shared.types import Language
from app.users.infrastructure.sqlite_repository import SqliteUserRepository


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch) -> str:
    path = str(tmp_path / "test.db")
    monkeypatch.setenv("DATABASE_PATH", path)
    get_settings.cache_clear()
    run_migrations()
    yield path
    get_settings.cache_clear()


async def test_start_for_problem_endpoint_creates_and_resumes(db_path: str) -> None:
    await SqliteUserRepository(db_path).ensure_default_user()
    await SqliteProblemRepository(db_path).save(
        Problem(
            id="p1", title="Two Sum", language=Language.PYTHON,
            difficulty="easy", status=ProblemStatus.AVAILABLE, created_at=datetime.now(UTC),
        )
    )

    with TestClient(app) as client:
        first = client.post("/api/problem-sessions/start-for-problem", json={"problem_id": "p1"})
        second = client.post("/api/problem-sessions/start-for-problem", json={"problem_id": "p1"})

    assert first.status_code == 200
    assert first.json()["problem_id"] == "p1"
    assert second.json()["id"] == first.json()["id"]
