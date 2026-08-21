import sqlite3
from pathlib import Path

import pytest

from app.evaluation.application.services import EvaluationService
from app.evaluation.infrastructure.sqlite_repository import SqliteEvaluationRepository
from app.execution.domain.models import ExecutionStatus, TestResult
from app.llm.schemas.coaching import CoachingFeedback
from app.problems.domain.models import Problem, ProblemStatus, ProblemTest, ProblemVersion
from app.problems.infrastructure.sqlite_repository import SqliteProblemRepository
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


async def _seed_problem(db_path: str) -> str:
    repo = SqliteProblemRepository(db_path)
    problem = Problem(
        id="p1",
        conceptual_id="sum-list",
        title="Sum List",
        language=Language.PYTHON,
        difficulty="easy",
        status=ProblemStatus.AVAILABLE,
        created_at="2026-01-01T00:00:00",
    )
    await repo.save(problem)
    version = ProblemVersion(
        id="v1",
        problem_id="p1",
        version=1,
        statement_md="Sum the list.",
        reference_solution="print(sum(int(x) for x in input().split()))",
        boilerplate="",
        tests=[ProblemTest(id="t1", input="1 2 3", output_hash="expectedhash")],
        created_at="2026-01-01T00:00:00",
    )
    await repo.save_version(version)
    return problem.id


async def test_evaluate_persists_deterministic_result_and_coaching_feedback(
    tmp_path: Path, db_path: str
) -> None:
    problem_id = await _seed_problem(db_path)
    code_file = tmp_path / "solution.py"
    code_file.write_text("print(sum(int(x) for x in input().split()))")

    executor = FakeCodeExecutor(
        [TestResult(id="t1", status=ExecutionStatus.PASSED, input="1 2 3", actual_output="6")]
    )
    llm = FakeLLMProvider(
        structured_responses=[CoachingFeedback(assessment="Nice work.", focus_areas=[])]
    )
    service = EvaluationService(
        SqliteEvaluationRepository(db_path), SqliteProblemRepository(db_path), executor, llm
    )

    evaluation = await service.evaluate(problem_id, "local-user", Language.PYTHON, str(code_file))

    assert evaluation.passed_tests == 1
    assert evaluation.total_tests == 1
    assert evaluation.feedback == "Nice work."


async def test_evaluate_degrades_gracefully_when_llm_unavailable(tmp_path: Path, db_path: str) -> None:
    problem_id = await _seed_problem(db_path)
    code_file = tmp_path / "solution.py"
    code_file.write_text("print(sum(int(x) for x in input().split()))")

    executor = FakeCodeExecutor(
        [TestResult(id="t1", status=ExecutionStatus.FAILED, input="1 2 3", actual_output="7")]
    )
    service = EvaluationService(
        SqliteEvaluationRepository(db_path), SqliteProblemRepository(db_path), executor, llm_provider=None
    )

    evaluation = await service.evaluate(problem_id, "local-user", Language.PYTHON, str(code_file))

    assert evaluation.passed_tests == 0
    assert evaluation.feedback is None
