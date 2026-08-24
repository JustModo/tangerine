"""The next-problem endpoint streams what it is really doing.

Preparing a problem is a bank lookup on a good day and generate -> validate -> patch ->
revalidate on a bad one. The UI used to guess at that with timers; these tests pin the
contract that lets it stop guessing.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.problems.domain.models import Problem, ProblemStatus
from app.problems.infrastructure.sqlite_repository import SqliteProblemRepository
from app.shared.config import get_settings
from app.shared.database import run_migrations
from app.shared.types import Language
from tests.db import seed_lesson_node


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch) -> str:
    path = str(tmp_path / "test.db")
    monkeypatch.setenv("DATABASE_PATH", path)
    get_settings.cache_clear()
    run_migrations()
    yield path
    get_settings.cache_clear()


async def test_a_bank_hit_streams_a_stage_then_the_session(db_path: str) -> None:
    seed_lesson_node(db_path, "node-1")
    await SqliteProblemRepository(db_path).save(
        Problem(
            id="p1", conceptual_id="c1", title="Bank Problem", language=Language.PYTHON,
            difficulty="easy", status=ProblemStatus.AVAILABLE, skill_ids=["skill-1"],
            created_at=datetime.now(timezone.utc),
        )
    )

    with TestClient(app) as client:
        response = client.post("/api/learning-plans/lp-node-1/problems/next")

    assert response.status_code == 200
    body = response.text
    assert '"stage": "selecting"' in body
    assert '"type": "session"' in body and '"problem_id": "p1"' in body
    # The client cannot tell a finished stream from a dropped one without this.
    assert body.rstrip().endswith("event: done\ndata: {}")


async def test_a_failure_keeps_its_own_message_instead_of_a_dead_stream(db_path: str) -> None:
    # The status line is already 200 by the time this is known, so a NotFoundError has to
    # travel as an error frame or the learner-facing sentence is lost.
    with TestClient(app) as client:
        response = client.post("/api/learning-plans/nope/problems/next")

    assert response.status_code == 200
    assert '"type": "error"' in response.text
    assert "not found" in response.text
