import sqlite3
from pathlib import Path

import pytest

from app.curriculum.application.services import CurriculumService
from app.curriculum.domain.models import LessonNodeStatus
from app.curriculum.infrastructure.sqlite_repository import SqliteLessonPlanRepository
from app.llm.domain.requests import ChatChunk, ToolCallResult
from app.llm.infrastructure.cache import SqliteLLMCache
from app.llm.schemas.curriculum import GeneratedCurriculum, GeneratedCurriculumNode
from app.llm.schemas.lesson_notes import GeneratedLessonNotes, LessonNoteStep
from app.llm.schemas.plan_edit import RevisedCurriculum, RevisedStep
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.revision.domain.models import RevisionCandidate
from app.sessions.application.services import SessionService
from app.sessions.domain.models import ChatRole
from app.sessions.infrastructure.sqlite_repository import SqliteSessionRepository
from app.shared.database import MIGRATIONS_DIR
from app.shared.errors import NotFoundError
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


async def test_session_create_and_add_message(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    service = SessionService(SqliteSessionRepository(db_path))

    session = await service.create_session(user.id)
    async for _ in service.add_message(session.id, "teach me prefix sums"):
        pass

    fetched = await service.get_session(session.id)
    assert fetched is not None
    assert len(fetched.messages) == 1
    assert fetched.messages[0].content == "teach me prefix sums"

    sessions = await service.list_sessions(user.id)
    assert [s.id for s in sessions] == [session.id]


async def test_list_for_session_returns_the_newest_plan_first(db_path: str) -> None:
    # There's no accept/supersede step any more — the most recently created plan IS the
    # session's active one, which is exactly what the home and chat screens read as plans[0].
    user = await SqliteUserRepository(db_path).ensure_default_user()
    sessions = SessionService(SqliteSessionRepository(db_path))
    session = await sessions.create_session(user.id)

    generated = GeneratedCurriculum(
        title="Prefix Sums",
        nodes=[GeneratedCurriculumNode(title="Fundamentals", skill="prefix-sum", difficulty=1)],
    )
    fake_llm = FakeLLMProvider(structured_responses=[generated, generated.model_copy()])
    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path), fake_llm, skill_repository=SqliteSkillRepository(db_path)
    )

    await curriculum.create_draft(session.id, "prefix sums", Language.PYTHON, "beginner")
    newer = await curriculum.create_draft(session.id, "prefix sums v2", Language.PYTHON, "beginner")

    plans = await curriculum.list_for_session(session.id)
    assert len(plans) == 2
    assert plans[0].id == newer.id


async def test_delete_session_cascades_to_chat_and_plans(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    sessions = SessionService(SqliteSessionRepository(db_path))
    session = await sessions.create_session(user.id)
    async for _ in sessions.add_message(session.id, "teach me prefix sums"):
        pass

    generated = GeneratedCurriculum(
        title="Prefix Sums",
        nodes=[GeneratedCurriculumNode(title="Fundamentals", skill="prefix-sum", difficulty=1)],
    )
    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path),
        FakeLLMProvider(structured_responses=[generated]),
        skill_repository=SqliteSkillRepository(db_path),
    )
    plan = await curriculum.create_draft(session.id, "prefix sums", Language.PYTHON, "beginner")

    await sessions.delete_session(session.id)

    assert await sessions.get_session(session.id) is None
    assert await curriculum.get(plan.id) is None


async def test_unclear_message_streams_a_real_clarifying_question(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    llm = FakeLLMProvider(
        chat_streams=[
            [
                ChatChunk(text_delta="Beginner or "),
                ChatChunk(text_delta="interview-level?"),
                ChatChunk(done=True),
            ]
        ]
    )
    service = SessionService(SqliteSessionRepository(db_path), llm)
    session = await service.create_session(user.id)

    events = [event async for event in service.add_message(session.id, "I want to get better at DSA")]

    fetched = await service.get_session(session.id)
    assert fetched is not None
    assert len(fetched.messages) == 2
    assert fetched.messages[0].role == ChatRole.USER
    assert fetched.messages[1].role == ChatRole.ASSISTANT
    assert fetched.messages[1].content == "Beginner or interview-level?"
    assert any(e["type"] == "text_delta" for e in events)
    assert events[-1]["type"] == "done"


async def test_generate_plan_tool_call_persists_system_message_and_generates(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    generated = GeneratedCurriculum(
        title="Prefix Sums",
        nodes=[GeneratedCurriculumNode(title="Fundamentals", skill="prefix-sum", difficulty=1)],
    )
    llm = FakeLLMProvider(
        structured_responses=[generated],
        chat_streams=[
            [
                ChatChunk(
                    tool_call=ToolCallResult(
                        name="generate_learning_plan",
                        args={"topic": "prefix sums", "language": "python", "level": "beginner"},
                    )
                ),
                ChatChunk(done=True),
            ],
            [ChatChunk(text_delta="Your plan for prefix sums is ready!"), ChatChunk(done=True)],
        ],
    )
    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path), llm, skill_repository=SqliteSkillRepository(db_path)
    )
    service = SessionService(SqliteSessionRepository(db_path), llm, curriculum)
    session = await service.create_session(user.id)

    events = [event async for event in service.add_message(session.id, "teach me prefix sums")]

    fetched = await service.get_session(session.id)
    assert fetched is not None
    assert len(fetched.messages) == 3  # user, SYSTEM "Generating...", closing ASSISTANT reply
    assert fetched.messages[1].role == ChatRole.SYSTEM
    assert "Generating" in fetched.messages[1].content
    assert fetched.messages[2].role == ChatRole.ASSISTANT
    assert "ready" in fetched.messages[2].content

    plans = await curriculum.list_for_session(session.id)
    assert len(plans) == 1
    assert plans[0].topic == "prefix sums"

    assert any(e["type"] == "tool_start" for e in events)


async def test_generate_plan_tool_call_says_updating_when_a_plan_already_exists(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    generated = GeneratedCurriculum(
        title="Prefix Sums",
        nodes=[GeneratedCurriculumNode(title="Fundamentals", skill="prefix-sum", difficulty=1)],
    )
    llm = FakeLLMProvider(structured_responses=[generated, generated.model_copy()])
    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path), llm, skill_repository=SqliteSkillRepository(db_path)
    )
    service = SessionService(SqliteSessionRepository(db_path), llm, curriculum)
    session = await service.create_session(user.id)
    await curriculum.create_draft(session.id, "prefix sums", Language.PYTHON, "beginner")

    llm._chat_streams = [
        [
            ChatChunk(
                tool_call=ToolCallResult(
                    name="generate_learning_plan",
                    args={"topic": "prefix sums v2", "language": "python", "level": "beginner"},
                )
            ),
            ChatChunk(done=True),
        ],
        [ChatChunk(text_delta="Updated!"), ChatChunk(done=True)],
    ]

    async for _ in service.add_message(session.id, "actually make it harder"):
        pass

    fetched = await service.get_session(session.id)
    assert fetched is not None
    assert "Updating" in fetched.messages[1].content


async def test_tool_followup_never_leaks_a_raw_tool_call_to_the_user(db_path: str) -> None:
    # The model sometimes answers a tool result by echoing another tool call as raw JSON.
    # That must never reach the chat: no text_delta is emitted and the persisted reply is
    # readable prose, not a JSON blob.
    user = await SqliteUserRepository(db_path).ensure_default_user()
    generated = GeneratedCurriculum(
        title="Prefix Sums",
        nodes=[GeneratedCurriculumNode(title="Fundamentals", skill="prefix-sum", difficulty=1)],
    )
    llm = FakeLLMProvider(
        structured_responses=[generated],
        chat_streams=[
            [
                ChatChunk(
                    tool_call=ToolCallResult(
                        name="generate_learning_plan",
                        args={"topic": "prefix sums", "language": "python", "level": "beginner"},
                    )
                ),
                ChatChunk(done=True),
            ],
            # The follow-up turn echoes a tool call as text instead of replying.
            [
                ChatChunk(text_delta='{\n  "name": "edit_learning_plan",'),
                ChatChunk(text_delta='\n  "arguments": {"instruction": "..."}\n}'),
                ChatChunk(done=True),
            ],
        ],
    )
    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path), llm, skill_repository=SqliteSkillRepository(db_path)
    )
    service = SessionService(SqliteSessionRepository(db_path), llm, curriculum)
    session = await service.create_session(user.id)

    events = [event async for event in service.add_message(session.id, "teach me prefix sums")]

    assert not [e for e in events if e["type"] == "text_delta"]
    done = next(e for e in events if e["type"] == "done")
    assert not done["content"].lstrip().startswith("{")
    assert "edit_learning_plan" not in done["content"]

    fetched = await service.get_session(session.id)
    assert fetched is not None
    assert not fetched.messages[-1].content.lstrip().startswith("{")


async def test_edit_plan_preserves_completed_steps_and_adds_new_ones(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    sessions = SessionService(SqliteSessionRepository(db_path))
    session = await sessions.create_session(user.id)

    original = GeneratedCurriculum(
        title="Prefix Sums",
        nodes=[
            GeneratedCurriculumNode(title="Fundamentals", skill="prefix-sum", difficulty=1),
            GeneratedCurriculumNode(title="Range queries", skill="range-query", difficulty=3),
        ],
    )
    # The revision keeps both existing skills verbatim (so their progress survives), bumps
    # range-query's difficulty, and inserts a brand new step.
    revised = RevisedCurriculum(
        steps=[
            RevisedStep(title="Fundamentals", skill="prefix-sum", difficulty="easy"),
            RevisedStep(title="Range queries", skill="range-query", difficulty="hard"),
            RevisedStep(title="2D prefix sums", skill="prefix-sum-2d", difficulty="hard"),
        ],
    )
    repo = SqliteLessonPlanRepository(db_path)
    curriculum = CurriculumService(
        repo,
        FakeLLMProvider(structured_responses=[original, revised]),
        skill_repository=SqliteSkillRepository(db_path),
    )
    plan = await curriculum.create_draft(session.id, "prefix sums", Language.PYTHON, "beginner")
    await repo.update_node_status(plan.nodes[0].id, LessonNodeStatus.DONE)

    edited = await curriculum.edit_plan(plan.id, "add a step on 2D prefix sums and make step 2 harder")

    assert len(edited.nodes) == 3
    # The completed step kept its identity (same row id) and its DONE status.
    assert edited.nodes[0].id == plan.nodes[0].id
    assert edited.nodes[0].status == LessonNodeStatus.DONE
    # The untouched-but-retargeted step also kept its row, with the new difficulty applied.
    assert edited.nodes[1].id == plan.nodes[1].id
    assert edited.nodes[1].difficulty == "hard"
    # The new step is genuinely new, and the plan stays startable rather than all-locked.
    assert edited.nodes[2].skill_name == "prefix-sum-2d"
    assert edited.nodes[1].status == LessonNodeStatus.AVAILABLE


async def test_lesson_notes_404_for_unknown_node(db_path: str) -> None:
    service = CurriculumService(
        SqliteLessonPlanRepository(db_path),
        FakeLLMProvider(),  # no responses queued — the LLM must never be reached
        skill_repository=SqliteSkillRepository(db_path),
    )

    with pytest.raises(NotFoundError):
        await service.get_node_notes("does-not-exist")


async def test_lesson_notes_refused_for_a_locked_node(db_path: str) -> None:
    # Reading ahead would generate (and pay for) notes for a node the learner may never
    # reach — the same rule the plan UI enforces by hiding the button on locked rows.
    user = await SqliteUserRepository(db_path).ensure_default_user()
    sessions = SessionService(SqliteSessionRepository(db_path))
    session = await sessions.create_session(user.id)
    generated = GeneratedCurriculum(
        title="Prefix Sums",
        nodes=[
            GeneratedCurriculumNode(title="Fundamentals", skill="prefix-sum", difficulty=1),
            GeneratedCurriculumNode(title="Range queries", skill="range-query", difficulty=2),
        ],
    )
    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path),
        FakeLLMProvider(structured_responses=[generated]),
        skill_repository=SqliteSkillRepository(db_path),
    )
    plan = await curriculum.create_draft(session.id, "prefix sums", Language.PYTHON, "beginner")

    locked = next(n for n in plan.nodes if n.status == LessonNodeStatus.LOCKED)
    with pytest.raises(NotFoundError):
        await curriculum.get_node_notes(locked.id)


async def test_lesson_notes_use_the_plans_language_and_level_and_cache(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    sessions = SessionService(SqliteSessionRepository(db_path))
    session = await sessions.create_session(user.id)
    generated = GeneratedCurriculum(
        title="Prefix Sums",
        nodes=[GeneratedCurriculumNode(title="Fundamentals", skill="prefix-sum", difficulty=1)],
    )
    notes = GeneratedLessonNotes(
        steps=[LessonNoteStep(title="The core idea", body_md="Keep a running total.")]
    )
    # One curriculum response + exactly one notes response: a second notes generation would
    # raise AssertionError, so the repeat call below proves the cache served it.
    llm = FakeLLMProvider(structured_responses=[generated, notes])
    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path),
        llm,
        skill_repository=SqliteSkillRepository(db_path),
        llm_cache=SqliteLLMCache(db_path),
    )
    plan = await curriculum.create_draft(session.id, "prefix sums", Language.PYTHON, "beginner")

    first = await curriculum.get_node_notes(plan.nodes[0].id)
    second = await curriculum.get_node_notes(plan.nodes[0].id)

    assert first.steps[0].title == "The core idea"
    assert first == second


class _RaisingRevisionService:
    async def get_revision_queue(self, user_id: str):
        raise RuntimeError("mastery lookup exploded")


class _StubRevisionService:
    def __init__(self, candidates) -> None:
        self._candidates = candidates

    async def get_revision_queue(self, user_id: str):
        return self._candidates


async def test_practice_record_tool_answers_from_the_real_record(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    llm = FakeLLMProvider(
        chat_streams=[
            [ChatChunk(tool_call=ToolCallResult(name="get_practice_record", args={}))],
            [ChatChunk(text_delta="Graphs is worth a look."), ChatChunk(done=True)],
        ]
    )
    candidate = RevisionCandidate(
        skill_id="s1", skill_name="graphs", reason="weak_skill", priority=2.0,
        mastery_score=0.1, days_since_seen=4.0,
    )
    service = SessionService(
        SqliteSessionRepository(db_path), llm, None, _StubRevisionService([candidate])
    )
    session = await service.create_session(user.id)

    events = [event async for event in service.add_message(session.id, "what am I weak in?")]

    # The follow-up turn is what carries the record back to the model.
    assert llm.last_chat_request is not None
    assert "graphs (0.10" in llm.last_chat_request.message
    assert events[-1]["type"] == "done"
    assert events[-1]["content"] == "Graphs is worth a look."
    # Read-only: no "Generating a learning plan..." note gets persisted.
    fetched = await service.get_session(session.id)
    assert fetched is not None
    assert [m.role for m in fetched.messages] == [ChatRole.USER, ChatRole.ASSISTANT]


async def test_a_broken_mastery_lookup_still_returns_a_reply(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    llm = FakeLLMProvider(
        chat_streams=[
            [ChatChunk(tool_call=ToolCallResult(name="get_practice_record", args={}))],
            [ChatChunk(done=True)],
        ]
    )
    service = SessionService(
        SqliteSessionRepository(db_path), llm, None, _RaisingRevisionService()
    )
    session = await service.create_session(user.id)

    events = [event async for event in service.add_message(session.id, "what should I do next?")]

    assert events[0]["type"] == "user_message"
    assert events[-1]["type"] == "done"
    assert events[-1]["content"]
