import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.curriculum.application.code_helper import CodeHelperService
from app.curriculum.domain.problem_session import ProblemSession, ProblemSessionStatus
from app.curriculum.infrastructure.sqlite_problem_session_repository import (
    SqliteProblemSessionRepository,
)
from app.llm.domain.requests import ChatChunk
from app.problems.domain.models import (
    Problem,
    ProblemExample,
    ProblemStatus,
    ProblemTest,
    ProblemVersion,
)
from app.problems.infrastructure.sqlite_repository import SqliteProblemRepository
from app.shared.database import MIGRATIONS_DIR
from app.shared.errors import NotFoundError
from app.shared.types import Language
from tests.fakes import FakeLLMProvider

REFERENCE_SOLUTION = "SECRET_REFERENCE_print(sum(nums))"
HIDDEN_TEST_INPUT = "SECRET_HIDDEN_INPUT_9 9 9"
PRE_CODE = "SECRET_PRE_nums = list(map(int, input().split()))"
POST_CODE = "SECRET_POST_print(solve(nums))"


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


async def _seed(db_path: str) -> str:
    problems = SqliteProblemRepository(db_path)
    await problems.save(
        Problem(
            id="p1",
            conceptual_id="sum-list",
            title="Sum List",
            language=Language.PYTHON,
            difficulty="easy",
            status=ProblemStatus.AVAILABLE,
            created_at="2026-01-01T00:00:00",
        )
    )
    await problems.save_version(
        ProblemVersion(
            id="v1",
            problem_id="p1",
            version=1,
            statement_md="Sum the list of integers.",
            reference_solution=REFERENCE_SOLUTION,
            user_code="def solve(nums): pass",
            pre_code=PRE_CODE,
            post_code=POST_CODE,
            constraints="1 <= n <= 100",
            examples=[ProblemExample(id="e1", input="1 2 3", output="6")],
            tests=[ProblemTest(id="t1", input=HIDDEN_TEST_INPUT, output_hash="abc")],
            created_at="2026-01-01T00:00:00",
        )
    )
    now = datetime.now(timezone.utc)
    sessions = SqliteProblemSessionRepository(db_path)
    await sessions.save(
        ProblemSession(
            id="ps1",
            lesson_node_id="n1",
            problem_id="p1",
            user_id="local-user",
            status=ProblemSessionStatus.IN_PROGRESS,
            created_at=now,
            updated_at=now,
        )
    )
    return "ps1"


def _service(db_path: str, llm: FakeLLMProvider) -> CodeHelperService:
    return CodeHelperService(
        SqliteProblemSessionRepository(db_path), SqliteProblemRepository(db_path), llm
    )


async def test_helper_context_never_leaks_problem_secrets(db_path: str) -> None:
    # The whole point of the feature's threat model: the helper sees the learner's code and
    # the public statement, and NEVER the reference solution, hidden test inputs, or the
    # pre/post harness — any of those hands the learner the answer.
    session_id = await _seed(db_path)
    llm = FakeLLMProvider(chat_streams=[[ChatChunk(text_delta="Looks good."), ChatChunk(done=True)]])
    service = _service(db_path, llm)

    async for _ in service.send_message(session_id, "review this", "def solve(nums): return 42"):
        pass

    sent = llm.last_chat_request
    assert sent is not None
    blob = sent.system_prompt + sent.message
    for secret in (REFERENCE_SOLUTION, HIDDEN_TEST_INPUT, PRE_CODE, POST_CODE):
        assert secret not in blob
    # ...while the things it legitimately needs ARE present.
    assert "def solve(nums): return 42" in blob
    assert "Sum the list of integers." in blob


async def test_helper_persists_history_and_replays_it(db_path: str) -> None:
    session_id = await _seed(db_path)
    llm = FakeLLMProvider(
        chat_streams=[
            [ChatChunk(text_delta="First answer."), ChatChunk(done=True)],
            [ChatChunk(text_delta="Second answer."), ChatChunk(done=True)],
        ]
    )
    service = _service(db_path, llm)

    async for _ in service.send_message(session_id, "why does this fail?", "code v1"):
        pass
    async for _ in service.send_message(session_id, "and now?", "code v2"):
        pass

    messages = await service.list_messages(session_id)
    assert [(m.role, m.content) for m in messages] == [
        ("user", "why does this fail?"),
        ("assistant", "First answer."),
        ("user", "and now?"),
        ("assistant", "Second answer."),
    ]
    # The second call must carry the first exchange as history, or the chat has no memory.
    assert [t.content for t in llm.last_chat_request.history] == [
        "why does this fail?",
        "First answer.",
    ]


async def test_helper_truncates_a_large_failing_run(db_path: str) -> None:
    session_id = await _seed(db_path)
    llm = FakeLLMProvider(chat_streams=[[ChatChunk(text_delta="ok"), ChatChunk(done=True)]])
    service = _service(db_path, llm)
    last_run = {
        "kind": "submit",
        "passed": 0,
        "total": 10,
        "results": [
            {"status": "FAILED", "input": f"case-{i}", "actual_output": f"out-{i}"}
            for i in range(10)
        ],
    }

    async for _ in service.send_message(session_id, "help", "some code", last_run):
        pass

    prompt = llm.last_chat_request.system_prompt
    # Only the first 3 failures are worth the tokens; a 10-case dump would swamp the prompt.
    assert prompt.count("their_output=") == 3
    assert "case-0" in prompt and "case-9" not in prompt


async def test_helper_404s_for_unknown_problem_session(db_path: str) -> None:
    service = _service(db_path, FakeLLMProvider())
    with pytest.raises(NotFoundError):
        async for _ in service.send_message("nope", "hi", ""):
            pass
