import sqlite3
from pathlib import Path

import pytest

from app.curriculum.application.services import CurriculumService
from app.curriculum.domain.models import LessonPlanStatus
from app.curriculum.infrastructure.sqlite_repository import SqliteLessonPlanRepository
from app.llm.domain.requests import ChatChunk, ToolCallResult
from app.llm.schemas.curriculum import GeneratedCurriculum, GeneratedCurriculumNode
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.sessions.application.services import SessionService
from app.sessions.domain.models import ChatRole
from app.sessions.infrastructure.sqlite_repository import SqliteSessionRepository
from app.shared.database import MIGRATIONS_DIR
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


async def test_curriculum_accept_supersedes_previous_plan(db_path: str) -> None:
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

    plan_a = await curriculum.create_draft(session.id, "prefix sums", Language.PYTHON, "beginner")
    await curriculum.accept(plan_a.id)

    plan_b = await curriculum.create_draft(session.id, "prefix sums v2", Language.PYTHON, "beginner")
    accepted_b = await curriculum.accept(plan_b.id)

    assert accepted_b.status == LessonPlanStatus.ACCEPTED

    refetched_a = await curriculum.get(plan_a.id)
    assert refetched_a is not None
    assert refetched_a.status == LessonPlanStatus.SUPERSEDED


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
