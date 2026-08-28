from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.curriculum.application.problem_sessions import ProblemSessionService
from app.curriculum.infrastructure.sqlite_problem_session_repository import (
    SqliteProblemSessionRepository,
)
from app.curriculum.infrastructure.sqlite_repository import SqliteLessonPlanRepository
from app.main import app
from app.problems.application.services import ProblemSelectionService
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


async def _seed(db_path: str, problem_id: str, language: Language = Language.PYTHON) -> None:
    await SqliteProblemRepository(db_path).save(
        Problem(
            id=problem_id,
            conceptual_id=f"c-{problem_id}",
            title="Two Sum",
            language=language,
            difficulty="easy",
            status=ProblemStatus.AVAILABLE,
            created_at=datetime.now(UTC),
        )
    )


async def test_all_problems_endpoint_paginates(db_path: str) -> None:
    await _seed(db_path, "p1")
    await _seed(db_path, "p2")

    with TestClient(app) as client:
        response = client.get("/api/problems/all", params={"page": 1, "page_size": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 1
    assert body["page"] == 1
    assert body["page_size"] == 1


async def test_all_problems_endpoint_does_not_get_shadowed_by_problem_id_route(db_path: str) -> None:
    # /problems/{problem_id} is registered too — /problems/all must not be swallowed by it.
    with TestClient(app) as client:
        response = client.get("/api/problems/all")

    assert response.status_code == 200
    assert response.json()["items"] == []


async def test_all_problems_endpoint_filters_by_language(db_path: str) -> None:
    await _seed(db_path, "p1", language=Language.PYTHON)
    await _seed(db_path, "p2", language=Language.JAVA)

    with TestClient(app) as client:
        response = client.get("/api/problems/all", params={"language": "java"})

    items = response.json()["items"]
    assert [item["id"] for item in items] == ["p2"]


async def test_all_problems_endpoint_marks_flagged_items(db_path: str) -> None:
    await SqliteUserRepository(db_path).ensure_default_user()
    await _seed(db_path, "p1")
    await _seed(db_path, "p2")
    problem_sessions = ProblemSessionService(
        SqliteLessonPlanRepository(db_path),
        SqliteProblemSessionRepository(db_path),
        ProblemSelectionService(SqliteProblemRepository(db_path)),
        None,  # unused: start_for_problem/set_flagged never generate
    )
    await problem_sessions.set_flagged_for_problem("local-user", "p1", True)

    with TestClient(app) as client:
        response = client.get("/api/problems/all")

    items = {item["id"]: item["flagged"] for item in response.json()["items"]}
    assert items == {"p1": True, "p2": False}
