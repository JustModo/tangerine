"""Test mode: one button, a randomly drawn interview-standard problem, no lesson node.

The stream contract matters as much as the problem — generation runs 30-90s with no cache,
so a silent stall and a real failure have to look different to the learner.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.curriculum.api.problem_sessions_router import get_service
from app.curriculum.application.problem_sessions import ProblemSessionService
from app.curriculum.infrastructure.sqlite_problem_session_repository import (
    SqliteProblemSessionRepository,
)
from app.curriculum.infrastructure.sqlite_repository import SqliteLessonPlanRepository
from app.main import app
from app.problems.application.services import ProblemSelectionService
from app.problems.domain.models import Problem, ProblemStatus
from app.problems.infrastructure.sqlite_repository import SqliteProblemRepository
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.shared.config import get_settings
from app.shared.database import run_migrations
from app.shared.types import Language
from tests.db import seed_users


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch) -> str:
    path = str(tmp_path / "test.db")
    monkeypatch.setenv("DATABASE_PATH", path)
    get_settings.cache_clear()
    run_migrations()
    seed_users(path, "local-user")
    yield path
    app.dependency_overrides.clear()
    get_settings.cache_clear()


class _StubValidation:
    """Stands in for a 30-90s generation, and records what the catalog actually drew."""

    def __init__(self, db_path: str, problem: Problem | None) -> None:
        self._db_path = db_path
        self._problem = problem
        self.calls: list[tuple] = []

    async def generate_and_validate(self, skill, language, difficulty, **kwargs):
        self.calls.append((skill, language, difficulty, kwargs.get("areas")))
        if kwargs.get("on_stage"):
            kwargs["on_stage"]("generating")
        if self._problem is not None:
            await SqliteProblemRepository(self._db_path).save(self._problem)
        return self._problem


def _install(db_path: str, validation) -> None:
    app.dependency_overrides[get_service] = lambda: ProblemSessionService(
        SqliteLessonPlanRepository(db_path),
        SqliteProblemSessionRepository(db_path),
        ProblemSelectionService(SqliteProblemRepository(db_path)),
        validation,
        SqliteSkillRepository(db_path),
    )


def _problem(db_path: str) -> Problem:
    from datetime import UTC, datetime

    return Problem(
        id="generated-1", title="Warehouse Restocking", language=Language.PYTHON,
        difficulty="medium", status=ProblemStatus.AVAILABLE, skill_ids=[],
        created_at=datetime.now(UTC),
    )


def test_a_test_problem_streams_its_stages_then_a_node_less_session(db_path: str) -> None:
    validation = _StubValidation(db_path, _problem(db_path))
    _install(db_path, validation)

    with TestClient(app) as client:
        response = client.post("/api/problem-sessions/test", json={"language": "python"})

    assert response.status_code == 200
    body = response.text
    assert '"stage": "generating"' in body
    assert '"type": "session"' in body
    # A test problem belongs to no plan, which is what hides the lesson tab.
    assert '"lesson_node_id": null' in body and '"lesson_plan_id": null' in body
    assert body.rstrip().endswith("event: done\ndata: {}")


def test_the_drawn_target_reaches_generation(db_path: str) -> None:
    validation = _StubValidation(db_path, _problem(db_path))
    _install(db_path, validation)

    with TestClient(app) as client:
        client.post("/api/problem-sessions/test", json={"language": "java"})

    skill, language, difficulty, areas = validation.calls[0]
    assert language == Language.JAVA
    assert difficulty in ("easy", "medium", "hard")
    assert areas, "generation ran untargeted"
    # Two of them, or the question collapses back to a single-technique exercise.
    assert len(areas) == 2 and areas[0] != areas[1]


def test_a_generation_that_gives_up_is_an_error_frame_not_a_dead_stream(db_path: str) -> None:
    _install(db_path, _StubValidation(db_path, None))

    with TestClient(app) as client:
        response = client.post("/api/problem-sessions/test", json={"language": "python"})

    # The 200 is already sent by the time this is known, so it can only travel as a frame.
    assert response.status_code == 200
    assert '"type": "error"' in response.text


def test_an_unsupported_language_is_rejected_before_any_generation(db_path: str) -> None:
    validation = _StubValidation(db_path, _problem(db_path))
    _install(db_path, validation)

    with TestClient(app) as client:
        response = client.post("/api/problem-sessions/test", json={"language": "rust"})

    assert response.status_code == 422
    assert validation.calls == []


def test_a_typed_topic_and_difficulty_reach_generation(db_path: str) -> None:
    validation = _StubValidation(db_path, _problem(db_path))
    _install(db_path, validation)

    with TestClient(app) as client:
        response = client.post(
            "/api/problem-sessions/test",
            json={"language": "python", "difficulty": "hard", "topic": "graphs"},
        )

    assert response.status_code == 200
    skill, _, difficulty, areas = validation.calls[0]
    assert skill == "graphs"
    assert difficulty == "hard"
    assert areas[0] == "graphs" and areas[1] != "graphs"


def test_omitting_them_still_draws_at_random(db_path: str) -> None:
    validation = _StubValidation(db_path, _problem(db_path))
    _install(db_path, validation)

    with TestClient(app) as client:
        client.post("/api/problem-sessions/test", json={"language": "python"})

    _, _, difficulty, areas = validation.calls[0]
    assert difficulty in ("easy", "medium", "hard")
    assert len(areas) == 2


def test_an_unsupported_difficulty_is_rejected(db_path: str) -> None:
    validation = _StubValidation(db_path, _problem(db_path))
    _install(db_path, validation)

    with TestClient(app) as client:
        response = client.post(
            "/api/problem-sessions/test", json={"language": "python", "difficulty": "insane"}
        )

    assert response.status_code == 422
    assert validation.calls == []
