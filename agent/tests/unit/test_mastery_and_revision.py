from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.llm.prompts.chat import mastery_context
from app.mastery.application.services import MasteryService
from app.mastery.domain.models import UserSkillState
from app.mastery.infrastructure.sqlite_repository import SqliteUserSkillStateRepository
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.revision.application.services import RevisionService, decayed_score, suggest_difficulty
from app.revision.domain.models import RevisionCandidate
from tests.db import apply_migrations, seed_skills, seed_users


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "test.db")
    apply_migrations(path)
    seed_users(path, "u1", "u2")
    seed_skills(path, "s1", "s2", "s3")
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


async def test_revision_queue_exposes_score_and_recency_for_the_chat_prompt(db_path: str) -> None:
    skill_repo = SqliteSkillRepository(db_path)
    skill_id = await skill_repo.ensure_skill("graphs")
    mastery_repo = SqliteUserSkillStateRepository(db_path)
    await mastery_repo.save(
        UserSkillState(
            user_id="u1",
            skill_id=skill_id,
            mastery_score=0.25,
            streak=0,
            last_seen_at=datetime.now(timezone.utc) - timedelta(days=3),
        )
    )

    queue = await RevisionService(mastery_repo, skill_repo).get_revision_queue("u1")

    assert queue[0].mastery_score == pytest.approx(0.25)
    assert queue[0].days_since_seen == pytest.approx(3.0, abs=0.1)


def _candidate(name: str, score: float, days: float = 1.0) -> RevisionCandidate:
    return RevisionCandidate(
        skill_id=name, skill_name=name, reason="review", priority=1.0,
        mastery_score=score, days_since_seen=days,
    )


def test_mastery_context_says_so_when_there_is_no_record() -> None:
    text = mastery_context([])
    assert "empty" in text
    assert "Weak" not in text


def test_mastery_context_buckets_by_score_and_caps_the_list() -> None:
    text = mastery_context(
        [_candidate("graphs", 0.1), _candidate("dp", 0.6), _candidate("arrays", 0.9)]
    )
    assert "Weak: graphs" in text
    assert "In progress: dp" in text
    assert "Solid: arrays" in text
    assert "more not listed" not in text

    capped = mastery_context([_candidate(f"s{i}", 0.1) for i in range(5)], limit=2)
    assert "s2" not in capped
    assert "plus 3 more not listed" in capped


async def test_help_reduces_what_a_pass_is_worth(db_path: str) -> None:
    service = MasteryService(SqliteUserSkillStateRepository(db_path))

    unaided = await service.record_result("u1", "s1", passed=True)
    assisted = await service.record_result("u2", "s1", passed=True, assistance=1.0)

    assert assisted.mastery_score < unaided.mastery_score
    # ...but never nothing: they did still solve it.
    assert assisted.mastery_score > 0


async def test_a_failure_is_a_failure_however_much_help_was_used(db_path: str) -> None:
    service = MasteryService(SqliteUserSkillStateRepository(db_path))
    await service.record_result("u1", "s1", passed=True)
    await service.record_result("u2", "s1", passed=True)

    unaided = await service.record_result("u1", "s1", passed=False)
    assisted = await service.record_result("u2", "s1", passed=False, assistance=1.0)

    assert assisted.mastery_score == pytest.approx(unaided.mastery_score)


async def test_a_secondary_skill_moves_less_than_the_primary(db_path: str) -> None:
    service = MasteryService(SqliteUserSkillStateRepository(db_path))

    primary = await service.record_result("u1", "s1", passed=True)
    secondary = await service.record_result("u1", "s2", passed=True, is_primary=False)

    assert secondary.mastery_score < primary.mastery_score


def test_a_stale_skill_stops_reading_as_mastered() -> None:
    assert decayed_score(0.9, days_since_seen=3) == pytest.approx(0.9)  # inside the grace window
    assert decayed_score(0.9, days_since_seen=120) < 0.6
    assert decayed_score(0.9, days_since_seen=10_000) == pytest.approx(0.27)  # floors, never zero


async def test_the_revision_queue_reports_the_decayed_score(db_path: str) -> None:
    skill_repo = SqliteSkillRepository(db_path)
    skill_id = await skill_repo.ensure_skill("long-forgotten")
    mastery_repo = SqliteUserSkillStateRepository(db_path)
    await mastery_repo.save(
        UserSkillState(
            user_id="u1",
            skill_id=skill_id,
            mastery_score=0.9,
            streak=3,
            last_seen_at=datetime.now(timezone.utc) - timedelta(days=200),
        )
    )

    queue = await RevisionService(mastery_repo, skill_repo).get_revision_queue("u1")

    assert queue[0].mastery_score < 0.5
    assert queue[0].reason == "weak_skill"
