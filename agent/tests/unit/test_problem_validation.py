import sqlite3
from pathlib import Path

import pytest

from app.execution.domain.models import ExecutionStatus, TestResult
from app.llm.schemas.problem import GeneratedExample, GeneratedProblem
from app.problems.application.validation import ProblemValidationService
from app.shared.hashing import hash_output
from app.problems.domain.models import ProblemStatus
from app.problems.infrastructure.sqlite_repository import SqliteProblemRepository
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.shared.database import MIGRATIONS_DIR
from app.shared.types import Language
from tests.fakes import FakeCodeExecutor, FakeLLMProvider


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


def _generated_problem() -> GeneratedProblem:
    return GeneratedProblem(
        title="Static Range Sum",
        statement_md="Given an array, answer sum queries.",
        difficulty="easy",
        skills=["prefix-sum"],
        boilerplate="def solve(nums): ...",
        reference_solution="def solve(nums): return sum(nums)",
        examples=[GeneratedExample(input="1 2 3", output="6")],
    )


async def test_generate_and_validate_marks_available_on_success(db_path: str) -> None:
    repo = SqliteProblemRepository(db_path)
    llm = FakeLLMProvider(structured_responses=[_generated_problem()])
    executor = FakeCodeExecutor(
        [TestResult(id="0", status=ExecutionStatus.PASSED, input="1 2 3", actual_output="6\n")]
    )
    service = ProblemValidationService(repo, llm, executor, SqliteSkillRepository(db_path))

    problem = await service.generate_and_validate("prefix-sum", Language.PYTHON, "easy")

    assert problem is not None
    assert problem.status == ProblemStatus.AVAILABLE

    version = await repo.get_latest_version(problem.id)
    assert version is not None
    assert len(version.tests) == 1
    # ground truth hash comes from the executor's actual_output, not the LLM's claimed output
    assert version.tests[0].output_hash == hash_output("6\n")


async def test_generate_and_validate_marks_invalid_when_reference_solution_errors(db_path: str) -> None:
    repo = SqliteProblemRepository(db_path)
    llm = FakeLLMProvider(structured_responses=[_generated_problem()])
    executor = FakeCodeExecutor(
        [TestResult(id="0", status=ExecutionStatus.ERROR, input="1 2 3", error="boom")]
    )
    service = ProblemValidationService(repo, llm, executor, SqliteSkillRepository(db_path))

    problem = await service.generate_and_validate("prefix-sum", Language.PYTHON, "easy")

    assert problem is None
    all_matching = await repo.list_by_skill(
        (await SqliteSkillRepository(db_path).ensure_skill("prefix-sum"))
    )
    assert len(all_matching) == 1
    assert all_matching[0].status == ProblemStatus.INVALID
