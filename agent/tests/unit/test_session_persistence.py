"""Every mutable field of a problem session must survive a save/reload round trip.

This exists because three separate upserts in this codebase have shipped with a column
missing from their ON CONFLICT DO UPDATE SET — the write reports success, the row never
changes, and the bug only surfaces later as something unrelated (a plan step that refuses
to advance). Asserting on the returned object cannot catch it; only a reload can.
"""

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.curriculum.domain.problem_session import ProblemSession, ProblemSessionStatus
from app.curriculum.infrastructure.sqlite_problem_session_repository import (
    SqliteProblemSessionRepository,
)
from tests.db import apply_migrations, seed_lesson_node


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "test.db")
    apply_migrations(path)
    seed_lesson_node(path, "node-1")
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO problems (id, conceptual_id, title, language, difficulty) "
        "VALUES ('p1', 'c1', 'T', 'python', 'easy')"
    )
    conn.commit()
    conn.close()
    return path


async def test_every_mutable_field_survives_a_reload(db_path: str) -> None:
    repo = SqliteProblemSessionRepository(db_path)
    now = datetime.now(UTC)
    session = ProblemSession(
        id=str(uuid.uuid4()),
        problem_id="p1",
        user_id="local-user",
        status=ProblemSessionStatus.NOT_STARTED,
        created_at=now,
        updated_at=now,
    )
    await repo.save(session)

    # Change everything that is allowed to change, in one update.
    mutated = session.model_copy(
        update={
            "lesson_node_id": "node-1",
            "lesson_plan_id": "lp-node-1",
            "source_code": "print(42)",
            "status": ProblemSessionStatus.COMPLETED,
            "flagged": True,
            "updated_at": datetime.now(UTC),
        }
    )
    await repo.save(mutated)

    stored = await repo.get(session.id)
    assert stored is not None
    dropped = [
        field
        for field in ("lesson_node_id", "lesson_plan_id", "source_code", "status", "flagged")
        if getattr(stored, field) != getattr(mutated, field)
    ]
    assert not dropped, f"save() silently dropped: {', '.join(dropped)}"


async def test_attaching_a_session_to_a_node_makes_it_findable_by_that_node(
    db_path: str,
) -> None:
    """The specific failure: a flagged problem's node-less session gets adopted onto a plan
    step. If the attach doesn't persist, get_by_node returns nothing forever — so the step
    re-adopts on every open and submitting never advances the plan."""
    repo = SqliteProblemSessionRepository(db_path)
    now = datetime.now(UTC)
    session = ProblemSession(
        id=str(uuid.uuid4()),
        problem_id="p1",
        user_id="local-user",
        status=ProblemSessionStatus.COMPLETED,
        created_at=now,
        updated_at=now,
    )
    await repo.save(session)
    assert await repo.get_by_node("node-1") is None

    await repo.save(session.model_copy(update={"lesson_node_id": "node-1"}))

    found = await repo.get_by_node("node-1")
    assert found is not None and found.id == session.id
