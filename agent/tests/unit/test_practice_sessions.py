"""Practice sessions: a problem for one skill, started from the revision queue rather than
from a plan. The distinguishing property is that they have no lesson node at all."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.curriculum.application.problem_sessions import ProblemSessionService
from app.curriculum.application.services import CurriculumService
from app.curriculum.domain.problem_session import ProblemSessionStatus
from app.curriculum.infrastructure.sqlite_problem_session_repository import (
    SqliteProblemSessionRepository,
)
from app.curriculum.infrastructure.sqlite_repository import SqliteLessonPlanRepository
from app.llm.schemas.curriculum import GeneratedCurriculum, GeneratedCurriculumNode
from app.llm.schemas.plan_edit import RevisedCurriculum, RevisedStep
from app.mastery.infrastructure.sqlite_repository import SqliteUserSkillStateRepository
from app.problems.application.services import ProblemSelectionService
from app.problems.domain.models import Problem, ProblemStatus
from app.problems.infrastructure.sqlite_repository import SqliteProblemRepository
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.sessions.application.services import SessionService
from app.sessions.infrastructure.sqlite_repository import SqliteSessionRepository
from app.shared.errors import ConflictError
from app.shared.types import Language
from tests.db import apply_migrations, seed_lesson_node, seed_skills, seed_users
from tests.fakes import FakeLLMProvider


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
        created_at=datetime.now(UTC),
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


async def test_a_session_started_outside_a_plan_belongs_to_no_lesson_node(db_path: str) -> None:
    problem = await _seed_bank_problem(db_path)

    session = await _service(db_path).start_for_problem("local-user", problem.id)

    assert session.lesson_node_id is None
    assert session.lesson_plan_id is None
    assert session.problem_id == "p1"
    # Round-trips: the nullable column is real, not just a permissive model.
    reloaded = await SqliteProblemSessionRepository(db_path).get(session.id)
    assert reloaded is not None and reloaded.lesson_node_id is None


async def test_submitting_a_node_less_session_touches_no_plan(db_path: str) -> None:
    problem = await _seed_bank_problem(db_path)
    service = _service(db_path)
    session = await service.start_for_problem("local-user", problem.id)

    # A plan-bound session would look up and advance its node here; this must not explode
    # on the None, and there is nothing for it to advance.
    updated = await service.record_submission(session.id, passed=True)

    assert updated.status == ProblemSessionStatus.COMPLETED


async def test_selection_never_repeats_a_problem_the_learner_has_seen(db_path: str) -> None:
    from tests.db import seed_lesson_node

    await _seed_bank_problem(db_path, "p1")
    seed_lesson_node(db_path, "node-1", user_id="local-user", skill_id="skill-1")
    service = _service(db_path)
    await service.start_for_problem("local-user", "p1")

    # The bank's only problem has already been served, so selection misses and generation
    # is required — which the fake refuses, proving the exclusion reached the query.
    with pytest.raises(AssertionError, match="bank problem"):
        await service.next_problem("lp-node-1", "local-user")


async def test_start_for_problem_creates_a_new_session(db_path: str) -> None:
    problem = await _seed_bank_problem(db_path)
    service = _service(db_path)

    session = await service.start_for_problem("local-user", problem.id)

    assert session.problem_id == problem.id
    assert session.lesson_node_id is None
    assert session.status == ProblemSessionStatus.NOT_STARTED


async def test_start_for_problem_resumes_an_existing_session(db_path: str) -> None:
    problem = await _seed_bank_problem(db_path)
    service = _service(db_path)
    first = await service.start_for_problem("local-user", problem.id)

    second = await service.start_for_problem("local-user", problem.id)

    assert second.id == first.id


async def test_set_flagged_for_problem_creates_a_session_if_needed(db_path: str) -> None:
    problem = await _seed_bank_problem(db_path)
    service = _service(db_path)

    session = await service.set_flagged_for_problem("local-user", problem.id, True)

    assert session.flagged is True
    assert session.problem_id == problem.id


async def test_set_flagged_for_problem_reuses_the_existing_session(db_path: str) -> None:
    problem = await _seed_bank_problem(db_path)
    service = _service(db_path)
    first = await service.start_for_problem("local-user", problem.id)

    flagged = await service.set_flagged_for_problem("local-user", problem.id, True)
    unflagged = await service.set_flagged_for_problem("local-user", problem.id, False)

    assert flagged.id == first.id
    assert unflagged.id == first.id
    assert unflagged.flagged is False


async def test_edit_plan_regenerates_a_step_whose_difficulty_actually_changed(db_path: str) -> None:
    # The bug: "make step 1 very hard" updated the node's difficulty column, but the
    # already-selected (or in-progress) EASY problem for that node kept being handed back —
    # nothing invalidated it, same root cause as the language-swap bug.
    sessions = SessionService(SqliteSessionRepository(db_path))
    session = await sessions.create_session("local-user")
    await SqliteProblemRepository(db_path).save(
        Problem(
            id="p-easy", conceptual_id="c-easy", title="Easy One", language=Language.PYTHON,
            difficulty="easy", status=ProblemStatus.AVAILABLE, skill_ids=["skill-1"],
            created_at=datetime.now(UTC),
        )
    )
    await SqliteProblemRepository(db_path).save(
        Problem(
            id="p-hard", conceptual_id="c-hard", title="Hard One", language=Language.PYTHON,
            difficulty="hard", status=ProblemStatus.AVAILABLE, skill_ids=["skill-1"],
            created_at=datetime.now(UTC),
        )
    )
    generated = GeneratedCurriculum(nodes=[GeneratedCurriculumNode(skill="skill-1", difficulty=1)])
    revised = RevisedCurriculum(steps=[RevisedStep(skill="skill-1", difficulty="hard")])
    llm = FakeLLMProvider(structured_responses=[generated, revised])
    plan_repo = SqliteLessonPlanRepository(db_path)
    curriculum = CurriculumService(
        plan_repo, llm, skill_repository=SqliteSkillRepository(db_path),
        problem_session_repository=SqliteProblemSessionRepository(db_path),
    )
    plan = await curriculum.create_draft(session.id, "topic", Language.PYTHON, "beginner")
    assert plan.nodes[0].difficulty == "easy"

    problem_sessions = ProblemSessionService(
        plan_repo, SqliteProblemSessionRepository(db_path),
        ProblemSelectionService(SqliteProblemRepository(db_path)), _NeverGenerates(),
        SqliteSkillRepository(db_path), mastery_repository=SqliteUserSkillStateRepository(db_path),
    )
    first = await problem_sessions.next_problem(plan.id, "local-user")
    assert first.problem_id == "p-easy"

    await curriculum.edit_plan(plan.id, "make step 1 very hard")
    second = await problem_sessions.next_problem(plan.id, "local-user")

    assert second.id != first.id
    assert second.problem_id == "p-hard"


async def test_edit_plan_leaves_an_unchanged_step_alone(db_path: str) -> None:
    # An edit to a different step ("add one more on hash maps") must not touch this
    # step's already-selected problem just because it was part of the same revision.
    sessions = SessionService(SqliteSessionRepository(db_path))
    session = await sessions.create_session("local-user")
    await _seed_bank_problem(db_path, "p-easy")
    generated = GeneratedCurriculum(nodes=[GeneratedCurriculumNode(skill="skill-1", difficulty=1)])
    revised = RevisedCurriculum(steps=[RevisedStep(skill="skill-1", difficulty="easy")])
    llm = FakeLLMProvider(structured_responses=[generated, revised])
    plan_repo = SqliteLessonPlanRepository(db_path)
    curriculum = CurriculumService(
        plan_repo, llm, skill_repository=SqliteSkillRepository(db_path),
        problem_session_repository=SqliteProblemSessionRepository(db_path),
    )
    plan = await curriculum.create_draft(session.id, "topic", Language.PYTHON, "beginner")

    problem_sessions = ProblemSessionService(
        plan_repo, SqliteProblemSessionRepository(db_path),
        ProblemSelectionService(SqliteProblemRepository(db_path)), _NeverGenerates(),
        SqliteSkillRepository(db_path), mastery_repository=SqliteUserSkillStateRepository(db_path),
    )
    first = await problem_sessions.next_problem(plan.id, "local-user")

    await curriculum.edit_plan(plan.id, "leave step 1 exactly as it is")
    second = await problem_sessions.next_problem(plan.id, "local-user")

    assert second.id == first.id


async def test_set_step_difficulty_regenerates_only_the_targeted_step(db_path: str) -> None:
    sessions = SessionService(SqliteSessionRepository(db_path))
    session = await sessions.create_session("local-user")
    for problem_id, difficulty in [("p-easy", "easy"), ("p-hard", "hard")]:
        await SqliteProblemRepository(db_path).save(
            Problem(
                id=problem_id, conceptual_id=f"c-{problem_id}", title=problem_id,
                language=Language.PYTHON, difficulty=difficulty, status=ProblemStatus.AVAILABLE,
                skill_ids=["skill-1"], created_at=datetime.now(UTC),
            )
        )
    generated = GeneratedCurriculum(nodes=[GeneratedCurriculumNode(skill="skill-1", difficulty=1)])
    plan_repo = SqliteLessonPlanRepository(db_path)
    curriculum = CurriculumService(
        plan_repo, FakeLLMProvider(structured_responses=[generated]),
        skill_repository=SqliteSkillRepository(db_path),
        problem_session_repository=SqliteProblemSessionRepository(db_path),
    )
    plan = await curriculum.create_draft(session.id, "topic", Language.PYTHON, "beginner")

    problem_sessions = ProblemSessionService(
        plan_repo, SqliteProblemSessionRepository(db_path),
        ProblemSelectionService(SqliteProblemRepository(db_path)), _NeverGenerates(),
        SqliteSkillRepository(db_path), mastery_repository=SqliteUserSkillStateRepository(db_path),
    )
    first = await problem_sessions.next_problem(plan.id, "local-user")
    assert first.problem_id == "p-easy"

    # No LLM response is queued beyond create_draft's — this must not call the LLM at all.
    updated = await curriculum.set_step_difficulty(plan.id, "1", "hard")
    assert updated.nodes[0].difficulty == "hard"

    second = await problem_sessions.next_problem(plan.id, "local-user")
    assert second.id != first.id
    assert second.problem_id == "p-hard"


async def test_set_step_difficulty_is_a_no_op_when_difficulty_is_unchanged(db_path: str) -> None:
    sessions = SessionService(SqliteSessionRepository(db_path))
    session = await sessions.create_session("local-user")
    await _seed_bank_problem(db_path, "p-easy")
    generated = GeneratedCurriculum(nodes=[GeneratedCurriculumNode(skill="skill-1", difficulty=1)])
    plan_repo = SqliteLessonPlanRepository(db_path)
    curriculum = CurriculumService(
        plan_repo, FakeLLMProvider(structured_responses=[generated]),
        skill_repository=SqliteSkillRepository(db_path),
        problem_session_repository=SqliteProblemSessionRepository(db_path),
    )
    plan = await curriculum.create_draft(session.id, "topic", Language.PYTHON, "beginner")
    problem_sessions = ProblemSessionService(
        plan_repo, SqliteProblemSessionRepository(db_path),
        ProblemSelectionService(SqliteProblemRepository(db_path)), _NeverGenerates(),
        SqliteSkillRepository(db_path), mastery_repository=SqliteUserSkillStateRepository(db_path),
    )
    first = await problem_sessions.next_problem(plan.id, "local-user")

    await curriculum.set_step_difficulty(plan.id, "1", "easy")
    second = await problem_sessions.next_problem(plan.id, "local-user")

    assert second.id == first.id


async def test_delete_unsubmitted_for_node_removes_not_started_and_in_progress_only(
    db_path: str,
) -> None:
    seed_lesson_node(db_path, "node-1", user_id="local-user", skill_id="skill-1")
    seed_lesson_node(db_path, "node-2", user_id="local-user", skill_id="skill-1")
    await _seed_bank_problem(db_path, "p1")
    await _seed_bank_problem(db_path, "p2")
    repo = SqliteProblemSessionRepository(db_path)
    problem_sessions = _service(db_path)

    not_started = await problem_sessions.next_problem("lp-node-1", "local-user")
    other_node_session = await problem_sessions.next_problem("lp-node-2", "local-user")

    await repo.delete_unsubmitted_for_node("node-1")

    assert await repo.get(not_started.id) is None
    # A different node's session is untouched.
    assert await repo.get(other_node_session.id) is not None


async def test_delete_unsubmitted_for_node_preserves_a_submitted_session(db_path: str) -> None:
    seed_lesson_node(db_path, "node-1", user_id="local-user", skill_id="skill-1")
    await _seed_bank_problem(db_path, "p1")
    repo = SqliteProblemSessionRepository(db_path)
    problem_sessions = _service(db_path)

    session = await problem_sessions.next_problem("lp-node-1", "local-user")
    await problem_sessions.save_code(session.id, "code")
    await problem_sessions.record_submission(session.id, passed=False)

    await repo.delete_unsubmitted_for_node("node-1")

    assert await repo.get(session.id) is not None


async def test_set_plan_language_regenerates_an_untouched_next_problem(db_path: str) -> None:
    # The bug: a language swap updated the plan row, but next_problem's get_by_node
    # short-circuit returned the pre-existing NOT_STARTED session in the OLD language
    # regardless — because nothing ever invalidated it. A NOT_STARTED session has had no
    # code saved against it, so nothing is lost by discarding it.
    seed_lesson_node(db_path, "node-1", user_id="local-user", skill_id="skill-1")
    plan_repo = SqliteLessonPlanRepository(db_path)
    await _seed_bank_problem(db_path, "p-py")
    await SqliteProblemRepository(db_path).save(
        Problem(
            id="p-java", conceptual_id="c-java", title="Bank Problem Java",
            language=Language.JAVA, difficulty="easy", status=ProblemStatus.AVAILABLE,
            skill_ids=["skill-1"], created_at=datetime.now(UTC),
        )
    )
    problem_sessions = _service(db_path)
    curriculum = CurriculumService(
        plan_repo, FakeLLMProvider(), problem_session_repository=SqliteProblemSessionRepository(db_path)
    )

    first = await problem_sessions.next_problem("lp-node-1", "local-user")
    assert first.problem_id == "p-py"

    await curriculum.set_plan_language("lp-node-1", Language.JAVA)
    second = await problem_sessions.next_problem("lp-node-1", "local-user")

    assert second.id != first.id
    assert second.problem_id == "p-java"


async def test_set_plan_language_also_regenerates_an_in_progress_session(db_path: str) -> None:
    # In-progress means code was saved but never submitted — realizing mid-attempt that
    # it's the wrong language is exactly the case a swap needs to unblock, so an
    # unsubmitted attempt is discarded just like an untouched one.
    seed_lesson_node(db_path, "node-1", user_id="local-user", skill_id="skill-1")
    plan_repo = SqliteLessonPlanRepository(db_path)
    await _seed_bank_problem(db_path, "p-py")
    await SqliteProblemRepository(db_path).save(
        Problem(
            id="p-java", conceptual_id="c-java", title="Bank Problem Java",
            language=Language.JAVA, difficulty="easy", status=ProblemStatus.AVAILABLE,
            skill_ids=["skill-1"], created_at=datetime.now(UTC),
        )
    )
    problem_sessions = _service(db_path)
    curriculum = CurriculumService(
        plan_repo, FakeLLMProvider(), problem_session_repository=SqliteProblemSessionRepository(db_path)
    )

    first = await problem_sessions.next_problem("lp-node-1", "local-user")
    await problem_sessions.save_code(first.id, "print('hi')")

    await curriculum.set_plan_language("lp-node-1", Language.JAVA)
    second = await problem_sessions.next_problem("lp-node-1", "local-user")

    assert second.id != first.id
    assert second.problem_id == "p-java"


async def test_set_plan_language_preserves_a_submitted_session(db_path: str) -> None:
    # A SUBMITTED (failed grading) or COMPLETED attempt is real, graded work — unlike
    # NOT_STARTED/IN_PROGRESS it must never be silently discarded by a language swap.
    seed_lesson_node(db_path, "node-1", user_id="local-user", skill_id="skill-1")
    plan_repo = SqliteLessonPlanRepository(db_path)
    await _seed_bank_problem(db_path, "p-py")
    problem_sessions = _service(db_path)
    curriculum = CurriculumService(
        plan_repo, FakeLLMProvider(), problem_session_repository=SqliteProblemSessionRepository(db_path)
    )

    first = await problem_sessions.next_problem("lp-node-1", "local-user")
    await problem_sessions.save_code(first.id, "print('hi')")
    await problem_sessions.record_submission(first.id, passed=False)

    await curriculum.set_plan_language("lp-node-1", Language.JAVA)
    second = await problem_sessions.next_problem("lp-node-1", "local-user")

    assert second.id == first.id
    assert second.problem_id == "p-py"


async def test_flagging_round_trips(db_path: str) -> None:
    await _seed_bank_problem(db_path)
    service = _service(db_path)
    session = await service.start_for_problem("local-user", "p1")

    assert (await service.set_flagged(session.id, True)).flagged is True
    sessions = await SqliteProblemSessionRepository(db_path).list_for_user("local-user")
    assert [s.flagged for s in sessions] == [True]
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
    assert len(await SqliteProblemSessionRepository(db_path).list_for_user("local-user")) == 1
    assert (await plan_repo.get_node("node-1")).status == LessonNodeStatus.IN_PROGRESS


def _curriculum(db_path: str) -> CurriculumService:
    return CurriculumService(
        SqliteLessonPlanRepository(db_path),
        FakeLLMProvider(),
        skill_repository=SqliteSkillRepository(db_path),
        problem_session_repository=SqliteProblemSessionRepository(db_path),
        problem_repository=SqliteProblemRepository(db_path),
    )


async def test_regenerating_a_step_retires_its_problem_and_serves_a_different_one(
    db_path: str,
) -> None:
    """The reported bug: asked to regenerate a step's question, the chat reworked the plan,
    changed nothing, and the step reopened the identical problem for ever."""
    seed_lesson_node(db_path, "node-1")
    await _seed_bank_problem(db_path, "p1")
    await _seed_bank_problem(db_path, "p2")
    problem_sessions = _service(db_path)

    first = await problem_sessions.next_problem("lp-node-1", "local-user")
    await _curriculum(db_path).regenerate_step_problem("lp-node-1", "1")
    second = await problem_sessions.next_problem("lp-node-1", "local-user")

    assert second.problem_id != first.problem_id
    retired = await SqliteProblemRepository(db_path).get(first.problem_id)
    assert retired is not None and retired.status == ProblemStatus.INVALID


async def test_regenerating_a_step_will_not_discard_graded_work(db_path: str) -> None:
    seed_lesson_node(db_path, "node-1")
    await _seed_bank_problem(db_path, "p1")
    problem_sessions = _service(db_path)

    session = await problem_sessions.next_problem("lp-node-1", "local-user")
    await problem_sessions.save_code(session.id, "code")
    await problem_sessions.record_submission(session.id, passed=False)

    with pytest.raises(ConflictError):
        await _curriculum(db_path).regenerate_step_problem("lp-node-1", "1")

    assert await SqliteProblemSessionRepository(db_path).get(session.id) is not None


async def test_regenerating_a_step_never_opened_says_so_rather_than_pretending(
    db_path: str,
) -> None:
    seed_lesson_node(db_path, "node-1")

    with pytest.raises(ConflictError):
        await _curriculum(db_path).regenerate_step_problem("lp-node-1", "1")
