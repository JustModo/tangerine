import sqlite3
from pathlib import Path

import pytest

from app.curriculum.application.services import CurriculumService
from app.curriculum.domain.models import LessonPlanStatus
from app.curriculum.infrastructure.sqlite_repository import SqliteLessonPlanRepository
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
    await service.add_message(session.id, ChatRole.USER, "teach me prefix sums")

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
    await sessions.add_message(session.id, ChatRole.USER, "teach me prefix sums")

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
