import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.mastery.application.services import MasteryService
from app.mastery.domain.models import UserSkillState
from app.mastery.infrastructure.sqlite_repository import SqliteUserSkillStateRepository
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.revision.application.services import RevisionService, suggest_difficulty
from app.shared.database import MIGRATIONS_DIR


def _apply_migrations(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        conn.executescript(path.read_text())
    conn.commit()
    conn.close()


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "test.db")
    _apply_migrations(path)
    return path


async def test_record_result_increases_and_decreases_score(db_path: str) -> None:
    service = MasteryService(SqliteUserSkillStateRepository(db_path))

    state = await service.record_result("u1", "s1", passed=True)
    assert state.mastery_score == pytest.approx(0.15)
    assert state.streak == 1

    state = await service.record_result("u1", "s1", passed=True)
    assert state.mastery_score == pytest.approx(0.30)
    assert state.streak == 2

    state = await service.record_result("u1", "s1", passed=False)
    assert state.mastery_score == pytest.approx(0.20)
    assert state.streak == 0


async def test_revision_queue_prioritizes_weak_and_overdue_skills(db_path: str) -> None:
    skill_repo = SqliteSkillRepository(db_path)
    weak_skill_id = await skill_repo.ensure_skill("weak-skill")
    strong_skill_id = await skill_repo.ensure_skill("strong-skill")

    mastery_repo = SqliteUserSkillStateRepository(db_path)
    now = datetime.now(timezone.utc)
    await mastery_repo.save(
        UserSkillState(user_id="u1", skill_id=weak_skill_id, mastery_score=0.1, streak=0, last_seen_at=now)
    )
    await mastery_repo.save(
        UserSkillState(
            user_id="u1",
            skill_id=strong_skill_id,
            mastery_score=0.95,
            streak=5,
            last_seen_at=now - timedelta(days=1),
        )
    )

    revision = RevisionService(mastery_repo, skill_repo)
    queue = await revision.get_revision_queue("u1")

    assert queue[0].skill_name == "weak-skill"
    assert queue[0].reason == "weak_skill"
    assert queue[0].priority > queue[1].priority


def test_suggest_difficulty_uses_mastery_when_available() -> None:
    assert suggest_difficulty(0.1, sequence_index=5) == "easy"
    assert suggest_difficulty(0.5, sequence_index=5) == "medium"
    assert suggest_difficulty(0.9, sequence_index=0) == "hard"
    assert suggest_difficulty(None, sequence_index=0) == "easy"
    assert suggest_difficulty(None, sequence_index=4) == "hard"
