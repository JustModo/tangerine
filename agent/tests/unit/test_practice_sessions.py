"""Practice sessions: a problem for one skill, started from the revision queue rather than
from a plan. The distinguishing property is that they have no lesson node at all."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.curriculum.application.problem_sessions import ProblemSessionService
from app.curriculum.domain.problem_session import ProblemSessionStatus
from app.curriculum.infrastructure.sqlite_problem_session_repository import (
    SqliteProblemSessionRepository,
)
from app.curriculum.infrastructure.sqlite_repository import SqliteLessonPlanRepository
from app.mastery.infrastructure.sqlite_repository import SqliteUserSkillStateRepository
from app.problems.application.services import ProblemSelectionService
from app.problems.domain.models import Problem, ProblemStatus
from app.problems.infrastructure.sqlite_repository import SqliteProblemRepository
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.shared.types import Language
from tests.db import apply_migrations, seed_skills, seed_users


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "test.db")
    apply_migrations(path)
    seed_users(path, "local-user")
    seed_skills(path, "skill-1")
    return path


class _NeverGenerates:
    """Generation is not what these tests are about — every case seeds the bank instead."""

    async def generate_and_validate(self, *args, **kwargs):
        raise AssertionError("should have found a bank problem")


async def _seed_bank_problem(db_path: str, problem_id: str = "p1") -> Problem:
    problem = Problem(
        id=problem_id,
        conceptual_id=f"c-{problem_id}",
        title="Bank Problem",
        language=Language.PYTHON,
        difficulty="easy",
        status=ProblemStatus.AVAILABLE,
        skill_ids=["skill-1"],
        created_at=datetime.now(timezone.utc),
    )
    await SqliteProblemRepository(db_path).save(problem)
    return problem


def _service(db_path: str, validation=None) -> ProblemSessionService:
    return ProblemSessionService(
        SqliteLessonPlanRepository(db_path),
        SqliteProblemSessionRepository(db_path),
        ProblemSelectionService(SqliteProblemRepository(db_path)),
        validation or _NeverGenerates(),
        SqliteSkillRepository(db_path),
        mastery_repository=SqliteUserSkillStateRepository(db_path),
    )


async def test_a_practice_session_belongs_to_no_lesson_node(db_path: str) -> None:
    await _seed_bank_problem(db_path)

    session = await _service(db_path).practice_problem("local-user", "skill-1", Language.PYTHON)

    assert session.lesson_node_id is None
    assert session.lesson_plan_id is None
    assert session.problem_id == "p1"
    # Round-trips: the nullable column is real, not just a permissive model.
    reloaded = await SqliteProblemSessionRepository(db_path).get(session.id)
    assert reloaded is not None and reloaded.lesson_node_id is None


async def test_submitting_a_practice_session_touches_no_plan(db_path: str) -> None:
    await _seed_bank_problem(db_path)
    service = _service(db_path)
    session = await service.practice_problem("local-user", "skill-1", Language.PYTHON)

    # A plan-bound session would look up and advance its node here; this must not explode
    # on the None, and there is nothing for it to advance.
    updated = await service.record_submission(session.id, passed=True)

    assert updated.status == ProblemSessionStatus.COMPLETED


async def test_practice_never_repeats_a_problem_the_learner_has_seen(db_path: str) -> None:
    await _seed_bank_problem(db_path, "p1")
    service = _service(db_path)
    await service.practice_problem("local-user", "skill-1", Language.PYTHON)

    # The bank's only problem is now excluded, so selection misses and generation is
    # required — which the fake refuses, proving the exclusion actually reached the query.
    with pytest.raises(AssertionError, match="bank problem"):
        await service.practice_problem("local-user", "skill-1", Language.PYTHON)


async def test_flagging_round_trips(db_path: str) -> None:
    await _seed_bank_problem(db_path)
    service = _service(db_path)
    session = await service.practice_problem("local-user", "skill-1", Language.PYTHON)

    assert (await service.set_flagged(session.id, True)).flagged is True
    assert [s.flagged for s in await service.list_for_user("local-user")] == [True]
    assert (await service.set_flagged(session.id, False)).flagged is False


async def test_starting_a_node_twice_resumes_instead_of_regenerating(db_path: str) -> None:
    # The Play button stays live on an IN_PROGRESS node, so this is called again every time
    # the learner returns to a step they already started. A second selection would hand
    # them a different problem and orphan the code they had written against the first.
    from app.curriculum.domain.models import LessonNodeStatus
    from tests.db import seed_lesson_node

    await _seed_bank_problem(db_path, "p1")
    await _seed_bank_problem(db_path, "p2")
    seed_lesson_node(db_path, "node-1", user_id="local-user", skill_id="skill-1")

    plan_repo = SqliteLessonPlanRepository(db_path)
    service = ProblemSessionService(
        plan_repo,
        SqliteProblemSessionRepository(db_path),
        ProblemSelectionService(SqliteProblemRepository(db_path)),
        _NeverGenerates(),
        SqliteSkillRepository(db_path),
        mastery_repository=SqliteUserSkillStateRepository(db_path),
    )

    first = await service.next_problem("lp-node-1", "local-user")
    second = await service.next_problem("lp-node-1", "local-user")

    assert second.id == first.id
    assert second.problem_id == first.problem_id
    # And no second row was written for the same node.
    assert len(await service.list_for_user("local-user")) == 1
    assert (await plan_repo.get_node("node-1")).status == LessonNodeStatus.IN_PROGRESS
