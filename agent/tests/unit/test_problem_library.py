"""The chat agent's view of problems the learner already has: finding them, and reopening
the EXACT one rather than generating a lookalike."""

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.curriculum.application.problem_sessions import ProblemSessionService
from app.curriculum.application.services import CurriculumService
from app.curriculum.domain.models import LessonNodeStatus
from app.curriculum.domain.problem_session import ProblemSession, ProblemSessionStatus
from app.curriculum.infrastructure.sqlite_problem_session_repository import (
    SqliteProblemSessionRepository,
)
from app.curriculum.infrastructure.sqlite_repository import SqliteLessonPlanRepository
from app.llm.domain.requests import ChatChunk, ToolCallResult
from app.problems.application.library import MAX_RESULTS, ProblemLibraryService
from app.problems.application.services import ProblemSelectionService
from app.problems.domain.models import Problem, ProblemStatus
from app.problems.infrastructure.sqlite_repository import SqliteProblemRepository
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.sessions.application.services import SessionService
from app.sessions.infrastructure.sqlite_repository import SqliteSessionRepository
from app.shared.database import MIGRATIONS_DIR
from app.shared.errors import ConflictError
from app.shared.types import Language
from app.users.infrastructure.sqlite_repository import SqliteUserRepository
from tests.fakes import FakeLLMProvider


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


async def _make_problem(
    db_path: str,
    title: str,
    skill: str = "prefix-sum",
    language: Language = Language.PYTHON,
) -> Problem:
    skill_id = await SqliteSkillRepository(db_path).ensure_skill(skill)
    problem = Problem(
        id=str(uuid.uuid4()),
        conceptual_id=str(uuid.uuid4()),
        title=title,
        language=language,
        difficulty="easy",
        status=ProblemStatus.AVAILABLE,
        skill_ids=[skill_id],
        tags=[skill],
        created_at=datetime.now(timezone.utc),
    )
    await SqliteProblemRepository(db_path).save(problem)
    return problem


async def _make_session(
    db_path: str,
    user_id: str,
    problem_id: str,
    status: ProblemSessionStatus = ProblemSessionStatus.COMPLETED,
    flagged: bool = False,
) -> ProblemSession:
    now = datetime.now(timezone.utc)
    session = ProblemSession(
        id=str(uuid.uuid4()),
        problem_id=problem_id,
        user_id=user_id,
        status=status,
        flagged=flagged,
        created_at=now,
        updated_at=now,
    )
    await SqliteProblemSessionRepository(db_path).save(session)
    return session


def _library(db_path: str) -> ProblemLibraryService:
    return ProblemLibraryService(
        SqliteProblemRepository(db_path),
        SqliteProblemSessionRepository(db_path),
        SqliteSkillRepository(db_path),
    )


async def test_scope_filters_by_what_the_learner_actually_did(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    solved = await _make_problem(db_path, "Solved One")
    failed = await _make_problem(db_path, "Failed One")
    flagged = await _make_problem(db_path, "Flagged One")
    untouched = await _make_problem(db_path, "Never Opened")

    await _make_session(db_path, user.id, solved.id, ProblemSessionStatus.COMPLETED)
    await _make_session(db_path, user.id, failed.id, ProblemSessionStatus.SUBMITTED)
    await _make_session(db_path, user.id, flagged.id, ProblemSessionStatus.NOT_STARTED, flagged=True)

    library = _library(db_path)

    titles = lambda entries: {e.title for e in entries}
    assert titles(await library.find(user.id, scope="solved")) == {"Solved One"}
    assert titles(await library.find(user.id, scope="flagged")) == {"Flagged One"}
    # A submitted-but-failed problem is the best revision candidate there is — dropping it
    # would hide exactly what the learner most needs to redo.
    assert titles(await library.find(user.id, scope="practised")) == {"Solved One", "Failed One"}
    # Nothing user-scoped ever includes a problem they have never opened.
    assert untouched.title not in titles(await library.find(user.id, scope="practised"))
    assert untouched.title in titles(await library.find(user.id, scope="all"))


async def test_find_never_returns_more_than_the_cap_or_any_statement(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    for index in range(MAX_RESULTS + 5):
        problem = await _make_problem(db_path, f"Problem {index}")
        await _make_session(db_path, user.id, problem.id)

    # Asking for more than the cap must still return the cap, not the number requested.
    entries = await _library(db_path).find(user.id, scope="practised", limit=100)

    assert len(entries) == MAX_RESULTS
    # The whole point of the thin entry: a list of statements would cost more context than
    # the answer is worth.
    assert not any(hasattr(entry, "statement_md") for entry in entries)


async def test_find_matches_a_rough_description(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    wanted = await _make_problem(db_path, "Two Sum Pairs")
    other = await _make_problem(db_path, "Merge Sorted Lists")
    await _make_session(db_path, user.id, wanted.id)
    await _make_session(db_path, user.id, other.id)

    entries = await _library(db_path).find(user.id, query="two sum", scope="practised")

    assert [entry.title for entry in entries] == ["Two Sum Pairs"]


async def test_skill_is_resolved_by_name_not_id(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    graph = await _make_problem(db_path, "Course Order", skill="graph traversal")
    array = await _make_problem(db_path, "Running Total", skill="prefix-sum")
    await _make_session(db_path, user.id, graph.id)
    await _make_session(db_path, user.id, array.id)

    # The user says "graphs"; the skill is stored as "graph traversal".
    entries = await _library(db_path).find(user.id, scope="practised", skill="graphs")

    assert [entry.title for entry in entries] == ["Course Order"]


async def test_an_unknown_skill_name_creates_no_skill_row(db_path: str) -> None:
    """_resolve_skill must never fall back to ensure_skill — that would write a junk row
    for every topic the learner mistypes."""
    user = await SqliteUserRepository(db_path).ensure_default_user()
    problem = await _make_problem(db_path, "Running Total")
    await _make_session(db_path, user.id, problem.id)
    before = len(await SqliteSkillRepository(db_path).list_all())

    await _library(db_path).find(user.id, scope="practised", skill="quantum tunnelling")

    assert len(await SqliteSkillRepository(db_path).list_all()) == before


async def test_stats_count_solved_problems_and_the_last_week(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    recent = await _make_problem(db_path, "Recent")
    old = await _make_problem(db_path, "Old")
    await _make_session(db_path, user.id, recent.id, ProblemSessionStatus.COMPLETED)

    stale = await _make_session(db_path, user.id, old.id, ProblemSessionStatus.COMPLETED)
    await SqliteProblemSessionRepository(db_path).save(
        stale.model_copy(update={"updated_at": datetime.now(timezone.utc) - timedelta(days=30)})
    )

    stats = await _library(db_path).stats(user.id)

    assert stats.solved_total == 2
    assert stats.solved_this_week == 1


async def _problem_session_service(db_path: str) -> ProblemSessionService:
    return ProblemSessionService(
        SqliteLessonPlanRepository(db_path),
        SqliteProblemSessionRepository(db_path),
        ProblemSelectionService(SqliteProblemRepository(db_path)),
        # No responses queued: any generation attempt raises, which is the assertion.
        _RaisingValidation(),
        skill_repository=SqliteSkillRepository(db_path),
    )


class _RaisingValidation:
    async def generate_and_validate(self, *args, **kwargs):
        raise AssertionError("a problem-bound node must never generate anything")


async def test_a_practice_plan_serves_the_exact_problems_with_no_llm_call(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    sessions = SqliteSessionRepository(db_path)
    session = await SessionService(sessions).create_session(user.id)
    first = await _make_problem(db_path, "Flagged One")
    second = await _make_problem(db_path, "Flagged Two")

    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path),
        # Queued with nothing — building a plan from existing problems must cost no call.
        FakeLLMProvider(),
        skill_repository=SqliteSkillRepository(db_path),
        problem_repository=SqliteProblemRepository(db_path),
    )
    plan = await curriculum.create_practice_plan(session.id, [first.id, second.id], "Flagged")

    assert [node.problem_id for node in plan.nodes] == [first.id, second.id]
    # The plan must be startable, not all-locked.
    assert plan.nodes[0].status == LessonNodeStatus.AVAILABLE

    service = await _problem_session_service(db_path)
    problem_session = await service.next_problem(plan.id, user.id)

    assert problem_session.problem_id == first.id


def _chat_service(db_path: str, llm, problem_session_service) -> SessionService:
    return SessionService(
        SqliteSessionRepository(db_path),
        llm,
        CurriculumService(
            SqliteLessonPlanRepository(db_path),
            llm,
            skill_repository=SqliteSkillRepository(db_path),
            problem_repository=SqliteProblemRepository(db_path),
        ),
        problem_session_service=problem_session_service,
        library_service=_library(db_path),
    )


async def test_a_lookups_ids_survive_into_the_next_turn(db_path: str) -> None:
    """THE regression this whole change exists for.

    The closing prose is told to keep ids out of sight, so if the lookup's ids are not
    carried forward some other way, a follow-up "yes" reaches the model with titles and
    nothing to act on — which is what made it re-search, re-offer, and guess.
    """
    user = await SqliteUserRepository(db_path).ensure_default_user()
    problem = await _make_problem(db_path, "Two Sum Pairs")
    await _make_session(db_path, user.id, problem.id, ProblemSessionStatus.COMPLETED)

    llm = FakeLLMProvider(
        chat_streams=[
            [
                ChatChunk(
                    tool_call=ToolCallResult(
                        name="find_problems", args={"query": "two sum", "scope": "practised"}
                    )
                ),
                ChatChunk(done=True),
            ],
            [
                ChatChunk(text_delta="You solved Two Sum Pairs. Add it to your plan?"),
                ChatChunk(done=True),
            ],
            [ChatChunk(text_delta="Sure."), ChatChunk(done=True)],
        ],
    )
    service = _chat_service(db_path, llm, await _problem_session_service(db_path))
    session = await service.create_session(user.id)

    [_ async for _ in service.add_message(session.id, "have I done a two sum one?")]
    # The visible reply must NOT leak the id...
    stored = await service.get_session(session.id)
    reply = [m for m in stored.messages if m.role.value == "assistant"][-1]
    assert problem.id not in reply.content

    [_ async for _ in service.add_message(session.id, "yes")]

    # ...but the turn that handled "yes" must still have been able to see it.
    history_text = "\n".join(turn.content for turn in llm.last_chat_request.history)
    assert problem.id in history_text


async def test_one_turn_can_look_up_then_act_on_what_it_found(db_path: str) -> None:
    """A compound ask — "yes remove everything and add that" — needs two tool calls in one
    turn. Without chaining the follow-up has no tools, so the model emits a tool call the
    guard blanks and the user gets a canned fallback instead of the thing they asked for."""
    user = await SqliteUserRepository(db_path).ensure_default_user()
    problem = await _make_problem(db_path, "Arithmetic Mean")
    await _make_session(db_path, user.id, problem.id, ProblemSessionStatus.COMPLETED)

    llm = FakeLLMProvider(
        chat_streams=[
            # Turn opens with a lookup...
            [
                ChatChunk(
                    tool_call=ToolCallResult(
                        name="find_problems", args={"query": "mean", "scope": "practised"}
                    )
                ),
                ChatChunk(done=True),
            ],
            # ...and the follow-up acts on it instead of only talking.
            [
                ChatChunk(
                    tool_call=ToolCallResult(
                        name="create_practice_plan",
                        args={"problem_ids": [problem.id], "topic": "Maths"},
                    )
                ),
                ChatChunk(done=True),
            ],
            [ChatChunk(text_delta="Rebuilt your plan around it."), ChatChunk(done=True)],
        ],
    )
    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path),
        llm,
        skill_repository=SqliteSkillRepository(db_path),
        problem_repository=SqliteProblemRepository(db_path),
    )
    service = SessionService(
        SqliteSessionRepository(db_path),
        llm,
        curriculum,
        problem_session_service=await _problem_session_service(db_path),
        library_service=_library(db_path),
    )
    session = await service.create_session(user.id)

    events = [
        e async for e in service.add_message(session.id, "yes remove everything and add that")
    ]

    plans = await curriculum.list_for_session(session.id)
    assert len(plans) == 1
    assert [node.problem_id for node in plans[0].nodes] == [problem.id]
    # The reply is the chained tool's, not the first tool's canned fallback.
    assert events[-1]["content"] == "Rebuilt your plan around it."


async def test_a_chain_stops_at_the_limit(db_path: str) -> None:
    """The chain must terminate in prose no matter what the model asks for, or one turn
    could call tools forever."""
    user = await SqliteUserRepository(db_path).ensure_default_user()
    problem = await _make_problem(db_path, "Arithmetic Mean")
    await _make_session(db_path, user.id, problem.id, ProblemSessionStatus.COMPLETED)

    lookup = [
        ChatChunk(tool_call=ToolCallResult(name="find_problems", args={"scope": "practised"})),
        ChatChunk(done=True),
    ]
    llm = FakeLLMProvider(
        # Three lookups offered; only two may run, so the third stream is never consumed.
        chat_streams=[lookup, lookup, lookup, [ChatChunk(text_delta="Done."), ChatChunk(done=True)]],
    )
    service = _chat_service(db_path, llm, await _problem_session_service(db_path))
    session = await service.create_session(user.id)

    events = [e async for e in service.add_message(session.id, "what have I solved?")]

    assert events[-1]["type"] == "done"
    # Two tool calls consumed two streams; the turn then had to speak.
    assert llm.last_chat_request.tools == []


async def test_saying_yes_puts_the_problem_on_the_plan(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    problem = await _make_problem(db_path, "Two Sum Pairs")
    await _make_session(db_path, user.id, problem.id, ProblemSessionStatus.COMPLETED)

    llm = FakeLLMProvider(
        chat_streams=[
            [
                ChatChunk(
                    tool_call=ToolCallResult(
                        name="edit_learning_plan",
                        args={"operation": "add_problem", "problem_id": problem.id},
                    )
                ),
                ChatChunk(done=True),
            ],
            [ChatChunk(text_delta="Added it to your plan."), ChatChunk(done=True)],
        ],
    )
    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path),
        llm,
        skill_repository=SqliteSkillRepository(db_path),
        problem_repository=SqliteProblemRepository(db_path),
    )
    session = await SessionService(SqliteSessionRepository(db_path)).create_session(user.id)
    seed = await _make_problem(db_path, "Seed Problem")
    plan = await curriculum.create_practice_plan(session.id, [seed.id], "Revision")

    service = SessionService(
        SqliteSessionRepository(db_path),
        llm,
        curriculum,
        problem_session_service=await _problem_session_service(db_path),
        library_service=_library(db_path),
    )
    [_ async for _ in service.add_message(session.id, "yes")]

    updated = await curriculum.get(plan.id)
    assert [node.problem_id for node in updated.nodes] == [seed.id, problem.id]


async def test_submitting_an_adopted_step_advances_the_plan(db_path: str) -> None:
    """The whole point of the flow: add a solved problem to a plan, solve it again, and the
    step must actually complete. It didn't, because the session's node link was never
    persisted, so record_submission reloaded it as node-less and skipped advancement."""
    user = await SqliteUserRepository(db_path).ensure_default_user()
    session = await SessionService(SqliteSessionRepository(db_path)).create_session(user.id)
    first = await _make_problem(db_path, "Arithmetic Mean")
    second = await _make_problem(db_path, "Follow Up")
    service = await _problem_session_service(db_path)
    # Flagging is what leaves a node-less session lying around for adoption.
    await service.set_flagged_for_problem(user.id, first.id, True)

    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path),
        FakeLLMProvider(),
        skill_repository=SqliteSkillRepository(db_path),
        problem_repository=SqliteProblemRepository(db_path),
    )
    plan = await curriculum.create_practice_plan(session.id, [first.id, second.id], "Revision")

    problem_session = await service.next_problem(plan.id, user.id)
    # Reloaded from the DB, not the returned object — that distinction is the bug.
    reloaded = await SqliteProblemSessionRepository(db_path).get(problem_session.id)
    assert reloaded is not None and reloaded.lesson_node_id == plan.nodes[0].id

    await service.record_submission(problem_session.id, passed=True)

    updated = await curriculum.get(plan.id)
    assert updated.nodes[0].status == LessonNodeStatus.DONE
    assert updated.nodes[1].status == LessonNodeStatus.AVAILABLE


async def test_revising_a_solved_problem_does_not_hand_back_the_answer(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    session = await SessionService(SqliteSessionRepository(db_path)).create_session(user.id)
    problem = await _make_problem(db_path, "Arithmetic Mean")
    service = await _problem_session_service(db_path)

    solved = await service.start_for_problem(user.id, problem.id)
    await service.save_code(solved.id, "def solve(): return 'my old answer'")
    await service.record_submission(solved.id, passed=True)

    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path),
        FakeLLMProvider(),
        skill_repository=SqliteSkillRepository(db_path),
        problem_repository=SqliteProblemRepository(db_path),
    )
    plan = await curriculum.create_practice_plan(session.id, [problem.id], "Revision")
    revision = await service.next_problem(plan.id, user.id)

    assert revision.source_code is None
    assert revision.status == ProblemSessionStatus.NOT_STARTED


async def test_an_unfinished_attempt_keeps_its_code_when_added_to_a_plan(db_path: str) -> None:
    """Only a SOLVED problem gets wiped — work in progress is still work."""
    user = await SqliteUserRepository(db_path).ensure_default_user()
    session = await SessionService(SqliteSessionRepository(db_path)).create_session(user.id)
    problem = await _make_problem(db_path, "Arithmetic Mean")
    service = await _problem_session_service(db_path)

    started = await service.start_for_problem(user.id, problem.id)
    await service.save_code(started.id, "half finished")

    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path),
        FakeLLMProvider(),
        skill_repository=SqliteSkillRepository(db_path),
        problem_repository=SqliteProblemRepository(db_path),
    )
    plan = await curriculum.create_practice_plan(session.id, [problem.id], "Revision")

    assert (await service.next_problem(plan.id, user.id)).source_code == "half finished"


async def test_play_opens_the_step_that_was_pressed(db_path: str) -> None:
    """Every row's Play used to start the first unfinished step, so pressing play on one
    row could open a different problem entirely."""
    user = await SqliteUserRepository(db_path).ensure_default_user()
    session = await SessionService(SqliteSessionRepository(db_path)).create_session(user.id)
    first = await _make_problem(db_path, "Step One")
    second = await _make_problem(db_path, "Step Two")
    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path),
        FakeLLMProvider(),
        skill_repository=SqliteSkillRepository(db_path),
        problem_repository=SqliteProblemRepository(db_path),
    )
    plan = await curriculum.create_practice_plan(session.id, [first.id, second.id], "Revision")
    # Unlock the second step so it is genuinely startable.
    await SqliteLessonPlanRepository(db_path).update_node_status(
        plan.nodes[1].id, LessonNodeStatus.AVAILABLE
    )
    service = await _problem_session_service(db_path)

    picked = await service.next_problem(plan.id, user.id, node_id=plan.nodes[1].id)

    assert picked.problem_id == second.id
    # No node id still means "continue from the first unfinished step".
    assert (await service.next_problem(plan.id, user.id)).problem_id == first.id


async def test_a_problem_added_to_a_plan_is_startable_immediately(db_path: str) -> None:
    """They asked for THIS problem by name — gating it behind an unfinished earlier step
    hands them a padlock instead of the thing they just asked for."""
    user = await SqliteUserRepository(db_path).ensure_default_user()
    session = await SessionService(SqliteSessionRepository(db_path)).create_session(user.id)
    busy = await _make_problem(db_path, "Already Going")
    wanted = await _make_problem(db_path, "The One They Asked For")
    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path),
        FakeLLMProvider(),
        skill_repository=SqliteSkillRepository(db_path),
        problem_repository=SqliteProblemRepository(db_path),
    )
    plan = await curriculum.create_practice_plan(session.id, [busy.id], "Revision")

    updated = await curriculum.add_problem_step(plan.id, wanted.id)

    added = next(n for n in updated.nodes if n.problem_id == wanted.id)
    assert added.status == LessonNodeStatus.AVAILABLE


async def test_adding_a_problem_already_on_the_plan_is_refused(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    session = await SessionService(SqliteSessionRepository(db_path)).create_session(user.id)
    problem = await _make_problem(db_path, "Two Sum Pairs")
    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path),
        FakeLLMProvider(),
        skill_repository=SqliteSkillRepository(db_path),
        problem_repository=SqliteProblemRepository(db_path),
    )
    plan = await curriculum.create_practice_plan(session.id, [problem.id], "Revision")

    # A conflict, not a 404 — "you already have this" must not reach the client dressed
    # as "this doesn't exist".
    with pytest.raises(ConflictError):
        await curriculum.add_problem_step(plan.id, problem.id)


async def test_a_problems_language_cannot_be_changed_after_it_is_stored(db_path: str) -> None:
    """The versions' code, tests and output hashes are all in the original language, so a
    row that claims a different one describes something the code isn't. The save must say
    no rather than silently drop the change — a save that quietly doesn't save is worse."""
    problem = await _make_problem(db_path, "Arithmetic Mean")

    with pytest.raises(ValueError, match="cannot be changed"):
        await SqliteProblemRepository(db_path).save(
            problem.model_copy(update={"language": Language.JAVA})
        )

    # Everything else on the row is still mutable.
    await SqliteProblemRepository(db_path).save(
        problem.model_copy(update={"title": "Arithmetic Mean II"})
    )
    stored = await SqliteProblemRepository(db_path).get(problem.id)
    assert stored is not None and stored.title == "Arithmetic Mean II"


async def test_language_narrows_what_they_solved(db_path: str) -> None:
    """The literal transcript failure: "revise problems i solved on python"."""
    user = await SqliteUserRepository(db_path).ensure_default_user()
    python_one = await _make_problem(db_path, "Arithmetic Mean")
    java_one = await _make_problem(db_path, "Bitmask Superstring", language=Language.JAVA)
    await _make_session(db_path, user.id, python_one.id, ProblemSessionStatus.COMPLETED)
    await _make_session(db_path, user.id, java_one.id, ProblemSessionStatus.COMPLETED)

    library = _library(db_path)

    assert [e.title for e in await library.find(user.id, scope="solved", language="python")] == [
        "Arithmetic Mean"
    ]
    assert len(await library.find(user.id, scope="solved")) == 2


async def test_a_flagged_problem_in_a_plan_keeps_its_single_session_and_flag(db_path: str) -> None:
    """Flagging creates a node-less session. Putting that problem in a plan must adopt it,
    not open a second row — otherwise the flag and the progress live on different rows."""
    user = await SqliteUserRepository(db_path).ensure_default_user()
    session = await SessionService(SqliteSessionRepository(db_path)).create_session(user.id)
    problem = await _make_problem(db_path, "Flagged One")

    service = await _problem_session_service(db_path)
    await service.set_flagged_for_problem(user.id, problem.id, True)

    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path),
        FakeLLMProvider(),
        skill_repository=SqliteSkillRepository(db_path),
        problem_repository=SqliteProblemRepository(db_path),
    )
    plan = await curriculum.create_practice_plan(session.id, [problem.id], "Flagged")
    problem_session = await service.next_problem(plan.id, user.id)

    all_sessions = await SqliteProblemSessionRepository(db_path).list_for_user(user.id)
    for_problem = [s for s in all_sessions if s.problem_id == problem.id]

    assert len(for_problem) == 1
    assert problem_session.flagged is True
    assert problem_session.lesson_node_id == plan.nodes[0].id
    # Re-doable: solving it before is recorded in mastery, not on this row.
    assert problem_session.status == ProblemSessionStatus.NOT_STARTED


async def test_set_problem_flag_tool_call_flags_the_problem(db_path: str) -> None:
    """The one tool with no coverage through the dispatch path — only its service method
    was exercised directly."""
    user = await SqliteUserRepository(db_path).ensure_default_user()
    problem = await _make_problem(db_path, "Merge Two Sorted Lists")

    llm = FakeLLMProvider(
        chat_streams=[
            [
                ChatChunk(
                    tool_call=ToolCallResult(
                        name="set_problem_flag",
                        args={"problem_id": problem.id, "flagged": True},
                    )
                ),
                ChatChunk(done=True),
            ],
            [ChatChunk(text_delta="Flagged it."), ChatChunk(done=True)],
        ],
    )
    service = _chat_service(db_path, llm, await _problem_session_service(db_path))
    session = await service.create_session(user.id)

    events = [e async for e in service.add_message(session.id, "flag that one")]

    sessions = await SqliteProblemSessionRepository(db_path).list_for_user(user.id)
    assert [s.flagged for s in sessions if s.problem_id == problem.id] == [True]
    assert events[-1]["type"] == "done"
