import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.curriculum.application.services import CurriculumService
from app.curriculum.domain.models import LessonNode, LessonNodeStatus, LessonPlan
from app.curriculum.infrastructure.sqlite_repository import SqliteLessonPlanRepository
from app.llm.domain.requests import ChatChunk, ToolCallResult
from app.llm.infrastructure.cache import SqliteLLMCache
from app.llm.schemas.curriculum import GeneratedCurriculum, GeneratedCurriculumNode
from app.llm.schemas.plan_edit import RevisedCurriculum, RevisedStep
from app.mastery.domain.models import UserSkillState
from app.mastery.infrastructure.sqlite_repository import SqliteUserSkillStateRepository
from app.problems.domain.models import Problem, ProblemExample, ProblemStatus, ProblemVersion
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.revision.domain.models import RevisionCandidate
from app.sessions.application.services import SessionService
from app.sessions.application.tool_results import plan_context, step_problem_context
from app.sessions.domain.models import ChatRole
from app.sessions.infrastructure.sqlite_repository import SqliteSessionRepository
from app.shared.config import get_settings
from app.shared.database import MIGRATIONS_DIR
from app.shared.errors import NotFoundError
from app.shared.types import Language
from app.users.infrastructure.sqlite_repository import SqliteUserRepository
from tests.fakes import FakeLLMProvider, fake_lesson_notes


def _apply_migrations(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        conn.executescript(path.read_text())
    conn.commit()
    conn.close()


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch) -> str:
    path = str(tmp_path / "test.db")
    _apply_migrations(path)
    # app.shared.preferences reads/writes through get_settings().database_path (same global
    # settings store as the Gemini key), so it needs to land in this test's own DB too.
    monkeypatch.setenv("DATABASE_PATH", path)
    get_settings.cache_clear()
    yield path
    get_settings.cache_clear()


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
        nodes=[GeneratedCurriculumNode(skill="prefix-sum", difficulty=1)],
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
        nodes=[GeneratedCurriculumNode(skill="prefix-sum", difficulty=1)],
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
        nodes=[GeneratedCurriculumNode(skill="prefix-sum", difficulty=1)],
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


async def test_generate_plan_tool_call_falls_back_to_configured_default_language(db_path: str) -> None:
    from app.shared.preferences import set_preference

    await set_preference("default_language", "java")
    user = await SqliteUserRepository(db_path).ensure_default_user()
    generated = GeneratedCurriculum(nodes=[GeneratedCurriculumNode(skill="prefix-sum", difficulty=1)])
    llm = FakeLLMProvider(
        structured_responses=[generated],
        chat_streams=[
            [
                ChatChunk(
                    tool_call=ToolCallResult(
                        name="generate_learning_plan", args={"topic": "prefix sums", "level": "beginner"}
                    )
                ),
                ChatChunk(done=True),
            ],
            [ChatChunk(text_delta="Ready!"), ChatChunk(done=True)],
        ],
    )
    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path), llm, skill_repository=SqliteSkillRepository(db_path)
    )
    service = SessionService(SqliteSessionRepository(db_path), llm, curriculum)
    session = await service.create_session(user.id)

    async for _ in service.add_message(session.id, "teach me prefix sums"):
        pass

    plans = await curriculum.list_for_session(session.id)
    assert len(plans) == 1
    assert plans[0].language == Language.JAVA


async def test_generate_plan_tool_call_says_updating_when_a_plan_already_exists(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    generated = GeneratedCurriculum(
        nodes=[GeneratedCurriculumNode(skill="prefix-sum", difficulty=1)],
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
        nodes=[GeneratedCurriculumNode(skill="prefix-sum", difficulty=1)],
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
        nodes=[
            GeneratedCurriculumNode(skill="prefix-sum", difficulty=1),
            GeneratedCurriculumNode(skill="range-query", difficulty=3),
        ],
    )
    # The revision keeps both existing skills verbatim (so their progress survives), bumps
    # range-query's difficulty, and inserts a brand new step.
    revised = RevisedCurriculum(
        steps=[
            RevisedStep(skill="prefix-sum", difficulty="easy"),
            RevisedStep(skill="range-query", difficulty="hard"),
            RevisedStep(skill="prefix-sum-2d", difficulty="hard"),
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


async def test_set_plan_language_changes_and_persists(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    sessions = SessionService(SqliteSessionRepository(db_path))
    session = await sessions.create_session(user.id)
    generated = GeneratedCurriculum(nodes=[GeneratedCurriculumNode(skill="prefix-sum", difficulty=1)])
    repo = SqliteLessonPlanRepository(db_path)
    curriculum = CurriculumService(
        repo,
        FakeLLMProvider(structured_responses=[generated]),
        skill_repository=SqliteSkillRepository(db_path),
    )
    plan = await curriculum.create_draft(session.id, "prefix sums", Language.JAVA, "beginner")

    updated = await curriculum.set_plan_language(plan.id, Language.PYTHON)

    assert updated.language == Language.PYTHON
    reloaded = await repo.get(plan.id)
    assert reloaded is not None
    assert reloaded.language == Language.PYTHON


async def test_set_plan_language_preserves_steps_and_completed_status(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    sessions = SessionService(SqliteSessionRepository(db_path))
    session = await sessions.create_session(user.id)
    generated = GeneratedCurriculum(
        nodes=[
            GeneratedCurriculumNode(skill="prefix-sum", difficulty=1),
            GeneratedCurriculumNode(skill="range-query", difficulty=2),
        ],
    )
    repo = SqliteLessonPlanRepository(db_path)
    curriculum = CurriculumService(
        repo,
        FakeLLMProvider(structured_responses=[generated]),
        skill_repository=SqliteSkillRepository(db_path),
    )
    plan = await curriculum.create_draft(session.id, "prefix sums", Language.JAVA, "beginner")
    await repo.update_node_status(plan.nodes[0].id, LessonNodeStatus.DONE)

    updated = await curriculum.set_plan_language(plan.id, Language.PYTHON)

    assert [n.id for n in updated.nodes] == [n.id for n in plan.nodes]
    assert updated.nodes[0].status == LessonNodeStatus.DONE
    assert updated.topic == plan.topic


async def test_edit_plan_tool_call_change_language_switches_the_plan(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    generated = GeneratedCurriculum(nodes=[GeneratedCurriculumNode(skill="prefix-sum", difficulty=1)])
    llm = FakeLLMProvider(structured_responses=[generated])
    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path), llm, skill_repository=SqliteSkillRepository(db_path)
    )
    service = SessionService(SqliteSessionRepository(db_path), llm, curriculum)
    session = await service.create_session(user.id)
    plan = await curriculum.create_draft(session.id, "prefix sums", Language.JAVA, "beginner")

    llm._chat_streams = [
        [
            ChatChunk(
                tool_call=ToolCallResult(
                    name="edit_learning_plan",
                    args={"operation": "change_language", "language": "python"},
                )
            ),
            ChatChunk(done=True),
        ],
        [ChatChunk(text_delta="Switched to Python."), ChatChunk(done=True)],
    ]

    events = [event async for event in service.add_message(session.id, "swap this to python")]

    updated = await curriculum.get(plan.id)
    assert updated is not None
    assert updated.language == Language.PYTHON
    assert [n.id for n in updated.nodes] == [n.id for n in plan.nodes]
    assert events[-1]["type"] == "done"


async def test_two_plan_edits_in_one_turn_leave_a_single_status_line(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    generated = GeneratedCurriculum(
        nodes=[
            GeneratedCurriculumNode(skill="prefix-sum", difficulty=1),
            GeneratedCurriculumNode(skill="range-query", difficulty=2),
        ],
    )
    llm = FakeLLMProvider(structured_responses=[generated])
    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path), llm, skill_repository=SqliteSkillRepository(db_path)
    )
    service = SessionService(SqliteSessionRepository(db_path), llm, curriculum)
    session = await service.create_session(user.id)
    plan = await curriculum.create_draft(session.id, "prefix sums", Language.JAVA, "beginner")

    llm._chat_streams = [
        [
            ChatChunk(
                tool_call=ToolCallResult(
                    name="edit_learning_plan", args={"operation": "remove_step", "step": "2"}
                )
            ),
            ChatChunk(done=True),
        ],
        [
            ChatChunk(
                tool_call=ToolCallResult(
                    name="edit_learning_plan",
                    args={"operation": "change_language", "language": "python"},
                )
            ),
            ChatChunk(done=True),
        ],
        [ChatChunk(text_delta="Dropped it and switched to Python."), ChatChunk(done=True)],
    ]

    events = [event async for event in service.add_message(session.id, "drop step 2 and make it python")]

    # Both edits ran...
    updated = await curriculum.get(plan.id)
    assert updated is not None
    assert [n.skill_name for n in updated.nodes] == ["prefix-sum"]
    assert updated.language == Language.PYTHON

    # ...and each showed its own label while the turn was in flight...
    assert [e["label"] for e in events if e["type"] == "tool_start"] == [
        "Removing step 2...",
        "Switching the plan to python...",
    ]

    # ...but the transcript keeps one line, rewritten to the last step, not two.
    fetched = await service.get_session(session.id)
    assert fetched is not None
    system_messages = [m for m in fetched.messages if m.role == ChatRole.SYSTEM]
    assert len(system_messages) == 1
    assert system_messages[0].content == "Switching the plan to python..."


async def test_edit_plan_tool_call_change_language_asks_for_an_unsupported_language(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    generated = GeneratedCurriculum(nodes=[GeneratedCurriculumNode(skill="prefix-sum", difficulty=1)])
    llm = FakeLLMProvider(structured_responses=[generated])
    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path), llm, skill_repository=SqliteSkillRepository(db_path)
    )
    service = SessionService(SqliteSessionRepository(db_path), llm, curriculum)
    session = await service.create_session(user.id)
    plan = await curriculum.create_draft(session.id, "prefix sums", Language.JAVA, "beginner")

    llm._chat_streams = [
        [
            ChatChunk(
                tool_call=ToolCallResult(
                    name="edit_learning_plan",
                    args={"operation": "change_language", "language": "rust"},
                )
            ),
            ChatChunk(done=True),
        ],
        [ChatChunk(text_delta="Rust isn't supported."), ChatChunk(done=True)],
    ]

    events = [event async for event in service.add_message(session.id, "swap this to rust")]

    assert events[-1]["type"] == "done"
    unchanged = await curriculum.get(plan.id)
    assert unchanged is not None
    assert unchanged.language == Language.JAVA


async def test_edit_plan_tool_call_change_step_difficulty(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    generated = GeneratedCurriculum(nodes=[GeneratedCurriculumNode(skill="prefix-sum", difficulty=1)])
    llm = FakeLLMProvider(structured_responses=[generated])
    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path), llm, skill_repository=SqliteSkillRepository(db_path)
    )
    service = SessionService(SqliteSessionRepository(db_path), llm, curriculum)
    session = await service.create_session(user.id)
    plan = await curriculum.create_draft(session.id, "prefix sums", Language.PYTHON, "beginner")
    assert plan.nodes[0].difficulty == "easy"

    llm._chat_streams = [
        [
            ChatChunk(
                tool_call=ToolCallResult(
                    name="edit_learning_plan",
                    args={"operation": "change_step_difficulty", "step": "1", "difficulty": "hard"},
                )
            ),
            ChatChunk(done=True),
        ],
        [ChatChunk(text_delta="Made step 1 harder."), ChatChunk(done=True)],
    ]
    events = [event async for event in service.add_message(session.id, "make step 1 harder")]

    updated = await curriculum.get(plan.id)
    assert updated is not None
    assert updated.nodes[0].difficulty == "hard"
    assert events[-1]["type"] == "done"


async def test_edit_plan_tool_call_add_step(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    generated = GeneratedCurriculum(nodes=[GeneratedCurriculumNode(skill="prefix-sum", difficulty=1)])
    llm = FakeLLMProvider(structured_responses=[generated])
    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path), llm, skill_repository=SqliteSkillRepository(db_path)
    )
    service = SessionService(SqliteSessionRepository(db_path), llm, curriculum)
    session = await service.create_session(user.id)
    plan = await curriculum.create_draft(session.id, "prefix sums", Language.PYTHON, "beginner")

    llm._chat_streams = [
        [
            ChatChunk(
                tool_call=ToolCallResult(
                    name="edit_learning_plan",
                    args={"operation": "add_step", "skill": "hash maps"},
                )
            ),
            ChatChunk(done=True),
        ],
        [ChatChunk(text_delta="Added it."), ChatChunk(done=True)],
    ]
    events = [event async for event in service.add_message(session.id, "add a step on hash maps")]

    updated = await curriculum.get(plan.id)
    assert updated is not None
    assert len(updated.nodes) == 2
    assert updated.nodes[1].skill_name == "hash maps"
    assert events[-1]["type"] == "done"


async def test_edit_plan_tool_call_remove_step(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    generated = GeneratedCurriculum(
        nodes=[
            GeneratedCurriculumNode(skill="prefix-sum", difficulty=1),
            GeneratedCurriculumNode(skill="range-query", difficulty=2),
        ],
    )
    llm = FakeLLMProvider(structured_responses=[generated])
    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path), llm, skill_repository=SqliteSkillRepository(db_path)
    )
    service = SessionService(SqliteSessionRepository(db_path), llm, curriculum)
    session = await service.create_session(user.id)
    plan = await curriculum.create_draft(session.id, "prefix sums", Language.PYTHON, "beginner")

    llm._chat_streams = [
        [
            ChatChunk(
                tool_call=ToolCallResult(
                    name="edit_learning_plan", args={"operation": "remove_step", "step": "2"}
                )
            ),
            ChatChunk(done=True),
        ],
        [ChatChunk(text_delta="Removed it."), ChatChunk(done=True)],
    ]
    events = [event async for event in service.add_message(session.id, "drop step 2")]

    updated = await curriculum.get(plan.id)
    assert updated is not None
    assert [n.skill_name for n in updated.nodes] == ["prefix-sum"]
    assert events[-1]["type"] == "done"


async def test_edit_plan_tool_call_reorder_step(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    generated = GeneratedCurriculum(
        nodes=[
            GeneratedCurriculumNode(skill="prefix-sum", difficulty=1),
            GeneratedCurriculumNode(skill="range-query", difficulty=2),
        ],
    )
    llm = FakeLLMProvider(structured_responses=[generated])
    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path), llm, skill_repository=SqliteSkillRepository(db_path)
    )
    service = SessionService(SqliteSessionRepository(db_path), llm, curriculum)
    session = await service.create_session(user.id)
    plan = await curriculum.create_draft(session.id, "prefix sums", Language.PYTHON, "beginner")

    llm._chat_streams = [
        [
            ChatChunk(
                tool_call=ToolCallResult(
                    name="edit_learning_plan",
                    args={"operation": "reorder_step", "step": "2", "to_position": 1},
                )
            ),
            ChatChunk(done=True),
        ],
        [ChatChunk(text_delta="Moved it."), ChatChunk(done=True)],
    ]
    events = [event async for event in service.add_message(session.id, "move step 2 to the start")]

    updated = await curriculum.get(plan.id)
    assert updated is not None
    assert [n.skill_name for n in updated.nodes] == ["range-query", "prefix-sum"]
    assert events[-1]["type"] == "done"


async def _two_step_plan(db_path: str) -> tuple[CurriculumService, LessonPlan]:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    sessions = SessionService(SqliteSessionRepository(db_path))
    session = await sessions.create_session(user.id)
    generated = GeneratedCurriculum(
        nodes=[
            GeneratedCurriculumNode(skill="arrays", difficulty=1),
            GeneratedCurriculumNode(skill="hash-maps", difficulty=2),
        ],
    )
    repo = SqliteLessonPlanRepository(db_path)
    curriculum = CurriculumService(
        repo,
        FakeLLMProvider(structured_responses=[generated]),
        skill_repository=SqliteSkillRepository(db_path),
    )
    plan = await curriculum.create_draft(session.id, "topic", Language.PYTHON, "beginner")
    return curriculum, plan


async def test_add_step_appends_a_new_step_without_touching_existing_ones(db_path: str) -> None:
    curriculum, plan = await _two_step_plan(db_path)

    updated = await curriculum.add_step(plan.id, "tries", difficulty="hard")

    assert len(updated.nodes) == 3
    assert updated.nodes[0].id == plan.nodes[0].id
    assert updated.nodes[1].id == plan.nodes[1].id
    assert updated.nodes[2].skill_name == "tries"
    assert updated.nodes[2].difficulty == "hard"


async def test_add_step_can_be_inserted_at_a_specific_position(db_path: str) -> None:
    curriculum, plan = await _two_step_plan(db_path)

    updated = await curriculum.add_step(plan.id, "tries", position=1)

    assert [n.skill_name for n in updated.nodes] == ["tries", "arrays", "hash-maps"]


async def test_remove_step_by_number_drops_it_and_reindexes(db_path: str) -> None:
    curriculum, plan = await _two_step_plan(db_path)

    updated = await curriculum.remove_step(plan.id, "1")

    assert [n.skill_name for n in updated.nodes] == ["hash-maps"]
    assert updated.nodes[0].sequence_index == 0


async def test_remove_step_by_skill_name_also_works(db_path: str) -> None:
    curriculum, plan = await _two_step_plan(db_path)

    updated = await curriculum.remove_step(plan.id, "hash-maps")

    assert [n.skill_name for n in updated.nodes] == ["arrays"]


async def test_remove_step_refuses_a_completed_step(db_path: str) -> None:
    curriculum, plan = await _two_step_plan(db_path)
    repo = SqliteLessonPlanRepository(db_path)
    await repo.update_node_status(plan.nodes[0].id, LessonNodeStatus.DONE)

    with pytest.raises(NotFoundError):
        await curriculum.remove_step(plan.id, "1")

    # Nothing was touched by the refused removal.
    unchanged = await curriculum.get(plan.id)
    assert unchanged is not None
    assert len(unchanged.nodes) == 2


async def test_reorder_step_moves_it_without_changing_its_identity(db_path: str) -> None:
    curriculum, plan = await _two_step_plan(db_path)

    updated = await curriculum.reorder_step(plan.id, "2", 1)

    assert [n.skill_name for n in updated.nodes] == ["hash-maps", "arrays"]
    assert updated.nodes[0].id == plan.nodes[1].id


async def test_resolving_an_unknown_step_raises(db_path: str) -> None:
    curriculum, plan = await _two_step_plan(db_path)

    with pytest.raises(NotFoundError):
        await curriculum.remove_step(plan.id, "graph-theory")

    with pytest.raises(NotFoundError):
        await curriculum.remove_step(plan.id, "99")


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
        nodes=[
            GeneratedCurriculumNode(skill="prefix-sum", difficulty=1),
            GeneratedCurriculumNode(skill="range-query", difficulty=2),
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
        nodes=[GeneratedCurriculumNode(skill="prefix-sum", difficulty=1)],
    )
    notes = fake_lesson_notes("The core idea")
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


async def test_lesson_notes_refresh_bypasses_the_cache_read_but_still_writes(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    sessions = SessionService(SqliteSessionRepository(db_path))
    session = await sessions.create_session(user.id)
    generated = GeneratedCurriculum(
        nodes=[GeneratedCurriculumNode(skill="prefix-sum", difficulty=1)],
    )
    original = fake_lesson_notes("First lesson")
    rewritten = fake_lesson_notes("Second lesson")
    # Exactly two lesson responses queued: a third generation would raise AssertionError,
    # so the final call below proves the refresh result was written back to the cache.
    llm = FakeLLMProvider(structured_responses=[generated, original, rewritten])
    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path),
        llm,
        skill_repository=SqliteSkillRepository(db_path),
        llm_cache=SqliteLLMCache(db_path),
    )
    plan = await curriculum.create_draft(session.id, "prefix sums", Language.PYTHON, "beginner")
    node_id = plan.nodes[0].id

    assert (await curriculum.get_node_notes(node_id)).steps[0].title == "First lesson"
    # refresh skips the cached entry and generates again...
    assert (await curriculum.get_node_notes(node_id, refresh=True)).steps[0].title == "Second lesson"
    # ...and replaced it, so the next plain read serves the regenerated lesson.
    assert (await curriculum.get_node_notes(node_id)).steps[0].title == "Second lesson"


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
        skill_id="s1",
        skill_name="graphs",
        reason="weak_skill",
        priority=2.0,
        mastery_score=0.1,
        days_since_seen=4.0,
    )
    service = SessionService(SqliteSessionRepository(db_path), llm, None, _StubRevisionService([candidate]))
    session = await service.create_session(user.id)

    events = [event async for event in service.add_message(session.id, "what am I weak in?")]

    # The follow-up turn is what carries the record back to the model.
    assert llm.last_chat_request is not None
    assert "graphs (id: s1, 0.10" in llm.last_chat_request.message
    assert events[-1]["type"] == "done"
    assert events[-1]["content"] == "Graphs is worth a look."
    # The label shows progress during the turn...
    assert [e["label"] for e in events if e["type"] == "tool_start"] == ["Checking your progress..."]
    # ...but a lookup changed nothing, so it leaves no line in the transcript.
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
    service = SessionService(SqliteSessionRepository(db_path), llm, None, _RaisingRevisionService())
    session = await service.create_session(user.id)

    events = [event async for event in service.add_message(session.id, "what should I do next?")]

    assert events[0]["type"] == "user_message"
    assert events[-1]["type"] == "done"
    assert events[-1]["content"]


async def test_a_plan_skips_steps_the_learner_has_already_mastered(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    sessions = SessionService(SqliteSessionRepository(db_path))
    session = await sessions.create_session(user.id)

    skill_repo = SqliteSkillRepository(db_path)
    known_id = await skill_repo.ensure_skill("arrays")
    mastery_repo = SqliteUserSkillStateRepository(db_path)
    await mastery_repo.save(
        UserSkillState(
            user_id=user.id,
            skill_id=known_id,
            mastery_score=0.95,
            streak=6,
            last_seen_at=datetime.now(UTC),
        )
    )

    generated = GeneratedCurriculum(
        nodes=[
            GeneratedCurriculumNode(skill="arrays", difficulty=1),
            GeneratedCurriculumNode(skill="prefix-sum", difficulty=3),
        ],
    )
    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path),
        FakeLLMProvider(structured_responses=[generated]),
        skill_repository=skill_repo,
        mastery_repository=mastery_repo,
    )

    plan = await curriculum.create_draft(
        session.id, "prefix sums", Language.PYTHON, "beginner", user_id=user.id
    )

    # The mastered step opens complete; the one they actually came for is startable, not
    # locked behind it.
    assert plan.nodes[0].status == LessonNodeStatus.DONE
    assert plan.nodes[1].status == LessonNodeStatus.AVAILABLE


async def test_a_plan_for_an_unknown_learner_starts_from_the_first_step(db_path: str) -> None:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    sessions = SessionService(SqliteSessionRepository(db_path))
    session = await sessions.create_session(user.id)

    generated = GeneratedCurriculum(
        nodes=[
            GeneratedCurriculumNode(skill="arrays", difficulty=1),
            GeneratedCurriculumNode(skill="prefix-sum", difficulty=3),
        ],
    )
    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path),
        FakeLLMProvider(structured_responses=[generated]),
        skill_repository=SqliteSkillRepository(db_path),
        mastery_repository=SqliteUserSkillStateRepository(db_path),
    )

    plan = await curriculum.create_draft(
        session.id, "prefix sums", Language.PYTHON, "beginner", user_id=user.id
    )

    assert [n.status for n in plan.nodes] == [
        LessonNodeStatus.AVAILABLE,
        LessonNodeStatus.LOCKED,
    ]


async def test_create_draft_drops_a_repeated_skill(db_path: str) -> None:
    """The prompt asks for distinct skills, but two steps on one skill are indistinguishable
    in the plan and draw from the same pool of questions."""
    user = await SqliteUserRepository(db_path).ensure_default_user()
    session = await SessionService(SqliteSessionRepository(db_path)).create_session(user.id)

    generated = GeneratedCurriculum(
        nodes=[
            GeneratedCurriculumNode(skill="prefix-sum", difficulty=1),
            GeneratedCurriculumNode(skill="Prefix-Sum", difficulty=2),
            GeneratedCurriculumNode(skill="sliding window", difficulty=2),
        ],
    )
    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path),
        FakeLLMProvider(structured_responses=[generated]),
        skill_repository=SqliteSkillRepository(db_path),
    )

    plan = await curriculum.create_draft(session.id, "prefix sums", Language.PYTHON, "beginner")

    assert [node.skill_name for node in plan.nodes] == ["prefix-sum", "sliding window"]
    assert [node.sequence_index for node in plan.nodes] == [0, 1]


async def _plan_and_service(db_path: str) -> tuple[SessionService, CurriculumService, str, LessonPlan]:
    user = await SqliteUserRepository(db_path).ensure_default_user()
    generated = GeneratedCurriculum(
        nodes=[
            GeneratedCurriculumNode(skill="prefix-sum", difficulty=1),
            GeneratedCurriculumNode(skill="range-query", difficulty=2),
        ],
    )
    llm = FakeLLMProvider(structured_responses=[generated])
    curriculum = CurriculumService(
        SqliteLessonPlanRepository(db_path), llm, skill_repository=SqliteSkillRepository(db_path)
    )
    service = SessionService(SqliteSessionRepository(db_path), llm, curriculum)
    session = await service.create_session(user.id)
    plan = await curriculum.create_draft(session.id, "prefix sums", Language.PYTHON, "beginner")
    return service, curriculum, session.id, plan


async def _run_edit(service: SessionService, llm: FakeLLMProvider, session_id: str, args: dict) -> list[dict]:
    llm._chat_streams = [
        [ChatChunk(tool_call=ToolCallResult(name="edit_learning_plan", args=args)), ChatChunk(done=True)],
        [ChatChunk(text_delta="Okay."), ChatChunk(done=True)],
    ]
    return [event async for event in service.add_message(session_id, "do the thing")]


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (
            {"operation": "change_step_difficulty", "step": "", "difficulty": "hard"},
            "missing which step or what difficulty",
        ),
        (
            {"operation": "change_step_difficulty", "step": "1", "difficulty": "spicy"},
            "missing which step or what difficulty",
        ),
        ({"operation": "add_step", "skill": ""}, "no skill/topic given"),
        ({"operation": "add_problem", "problem_id": ""}, "no problem id given"),
        ({"operation": "remove_step", "step": ""}, "no step named to remove"),
        ({"operation": "reorder_step", "step": "1"}, "missing which step or where to move it"),
        (
            {"operation": "reorder_step", "step": "", "to_position": 1},
            "missing which step or where to move it",
        ),
    ],
)
async def test_edit_plan_refuses_incomplete_arguments(db_path: str, args: dict, expected: str) -> None:
    """Every NOT RUN validation branch: nothing changes, the model is told why in the exact
    words it acts on, and the turn still completes."""
    service, curriculum, session_id, plan = await _plan_and_service(db_path)
    before = [n.skill_name for n in (await curriculum.get(plan.id)).nodes]

    events = await _run_edit(service, service._llm_provider, session_id, args)

    after = await curriculum.get(plan.id)
    assert [n.skill_name for n in after.nodes] == before
    followup = service._llm_provider.last_chat_request.message
    assert "NOT RUN" in followup and expected in followup
    assert events[-1]["type"] == "done"


async def test_edit_plan_refuses_an_operation_that_does_not_exist(db_path: str) -> None:
    """It used to rework instead. A request this chat cannot serve then came back as a
    whole-plan rework that changed nothing and reported success, and the model told the
    user it had fixed the thing they asked about."""
    service, curriculum, session_id, _ = await _plan_and_service(db_path)
    called: list[str] = []

    async def fake_edit_plan(plan_id: str, instruction: str):
        called.append(instruction)
        return await curriculum.get(plan_id)

    curriculum.edit_plan = fake_edit_plan

    events = await _run_edit(
        service, service._llm_provider, session_id, {"operation": "nonsense", "instruction": "mix it up"}
    )

    assert called == []
    followup = service._llm_provider.last_chat_request.message
    assert "NOT RUN" in followup and "nonsense" in followup
    assert "regenerate_problem" in followup
    assert events[-1]["type"] == "done"


async def test_a_rework_that_changed_nothing_is_reported_as_nothing(db_path: str) -> None:
    """The unfalsifiable result string: 'Updated the plan' was emitted even when the rework
    returned the identical plan, and the model narrated a fix that never happened."""
    service, curriculum, session_id, _ = await _plan_and_service(db_path)

    async def fake_edit_plan(plan_id: str, instruction: str):
        return await curriculum.get(plan_id)

    curriculum.edit_plan = fake_edit_plan

    await _run_edit(
        service, service._llm_provider, session_id, {"operation": "rework", "instruction": "fix it"}
    )

    followup = service._llm_provider.last_chat_request.message
    assert "NOT CHANGED" in followup
    assert "Updated the plan" not in followup


async def test_edit_plan_missing_operation_falls_back_to_rework(db_path: str) -> None:
    service, curriculum, session_id, plan = await _plan_and_service(db_path)
    called: list[str] = []

    async def fake_edit_plan(plan_id: str, instruction: str):
        called.append(instruction)
        return await curriculum.get(plan_id)

    curriculum.edit_plan = fake_edit_plan

    await _run_edit(service, service._llm_provider, session_id, {})

    assert called == ["do the thing"]


def _plan_with_steps(count: int = 9) -> LessonPlan:
    now = datetime.now(UTC)
    return LessonPlan(
        id="plan-1",
        session_id="session-1",
        topic="dynamic programming",
        language=Language.PYTHON,
        level="interview",
        version=1,
        created_at=now,
        nodes=[
            LessonNode(
                id=f"node-{i}",
                lesson_plan_id="plan-1",
                skill_id=f"skill-{i}",
                skill_name=f"step {i} skill",
                sequence_index=i,
                status=LessonNodeStatus.LOCKED,
                created_at=now,
            )
            for i in range(count)
        ],
    )


def test_plan_context_lists_every_step_in_order() -> None:
    """The bug this replaced: asked what was on a nine-step plan, the model had no plan in
    context at all and answered off the find_problems memo, naming five problems."""
    text = plan_context(_plan_with_steps())

    assert "9 steps" in text
    for i in range(9):
        assert f"{i + 1}. step {i} skill" in text


def test_plan_context_refuses_to_describe_a_plan_that_does_not_exist() -> None:
    assert "NO PLAN EXISTS" in plan_context(None)


def test_step_problem_context_shows_the_statement_and_every_example() -> None:
    """What the agent could not see: asked whether step 5's test cases matched its
    statement, it had only the title, and agreed with a complaint it never checked."""
    node = _plan_with_steps(1).nodes[0]
    problem = Problem(
        id="p1",
        title="Longest Mountain Peak Subsequence",
        language=Language.PYTHON,
        difficulty="medium",
        status=ProblemStatus.AVAILABLE,
        created_at=datetime.now(UTC),
    )
    version = ProblemVersion(
        id="v1",
        problem_id="p1",
        version=1,
        statement_md="Find the longest mountain subsequence.",
        reference_solution="print(0)",
        constraints="3 <= n <= 1000",
        examples=[
            ProblemExample(id="e1", problem_version_id="v1", input="1 3 2 5 4 1", output="5"),
            ProblemExample(id="e2", problem_version_id="v1", input="1 2 3 4 5", output="0"),
        ],
        created_at=datetime.now(UTC),
    )

    text = step_problem_context(node, problem, version)

    assert "Find the longest mountain subsequence." in text
    assert "3 <= n <= 1000" in text
    assert "'1 3 2 5 4 1' -> output '5'" in text
    assert "'1 2 3 4 5' -> output '0'" in text
    # The reference solution must never reach the model — it is the answer.
    assert "print(0)" not in text


def test_step_problem_context_refuses_to_describe_a_step_with_no_question_yet() -> None:
    node = _plan_with_steps(1).nodes[0]

    assert "HAS NO QUESTION YET" in step_problem_context(node, None, None)


def _expected_tools(has_revision, has_library, has_sessions, has_curriculum, existing_plan, user_id):
    """The gating rules spelled out independently of the implementation, so a registry that
    mis-transcribes one is caught rather than silently hiding a tool from the model."""
    names = ["generate_learning_plan"]
    if existing_plan:
        names += ["edit_learning_plan", "get_learning_plan"]
    if has_revision and user_id:
        names.append("get_practice_record")
    if has_library and has_sessions and user_id:
        names += ["find_problems", "set_problem_flag"]
    if has_library and has_curriculum and user_id:
        names.append("create_practice_plan")
    return names


@pytest.mark.parametrize("existing_plan", [False, True])
@pytest.mark.parametrize("user_id", [None, "local-user"])
@pytest.mark.parametrize("wired", [False, True])
def test_tools_offered_match_the_gating_rules(db_path, existing_plan, user_id, wired):
    sentinel = object()
    service = SessionService(
        SqliteSessionRepository(db_path),
        curriculum_service=sentinel if wired else None,
        revision_service=sentinel if wired else None,
        problem_session_service=sentinel if wired else None,
        library_service=sentinel if wired else None,
    )

    plan = _plan_with_steps() if existing_plan else None
    offered = [t.name for t in service._tools_for(plan, user_id)]

    assert offered == _expected_tools(wired, wired, wired, wired, existing_plan, user_id)
