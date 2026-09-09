from pathlib import Path

import pytest

from app.evaluation.application.services import EvaluationService
from app.evaluation.domain.models import AttemptMetrics
from app.evaluation.infrastructure.sqlite_repository import SqliteEvaluationRepository
from app.execution.domain.models import ExecutionStatus, TestResult
from app.problems.domain.models import Problem, ProblemStatus, ProblemTest
from app.problems.infrastructure.sqlite_repository import SqliteProblemRepository
from app.shared.types import Language
from tests.db import apply_migrations, seed_users
from tests.fakes import FakeCodeExecutor


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "test.db")
    apply_migrations(path)
    seed_users(path, "local-user")
    return path


async def _seed_problem(db_path: str) -> str:
    repo = SqliteProblemRepository(db_path)
    problem = Problem(
        id="p1",
        title="Sum List",
        language=Language.PYTHON,
        difficulty="easy",
        status=ProblemStatus.AVAILABLE,
        statement_md="Sum the list.",
        reference_solution="print(sum(int(x) for x in input().split()))",
        user_code="",
        pre_code="",
        post_code="",
        tests=[ProblemTest(id="t1", input="1 2 3", output_hash="expectedhash")],
        created_at="2026-01-01T00:00:00",
    )
    await repo.save(problem)
    return problem.id


async def test_evaluate_persists_deterministic_result(db_path: str) -> None:
    problem_id = await _seed_problem(db_path)
    code = "print(sum(int(x) for x in input().split()))"

    executor = FakeCodeExecutor(
        [TestResult(id="t1", status=ExecutionStatus.PASSED, input="1 2 3", actual_output="6")]
    )
    service = EvaluationService(
        SqliteEvaluationRepository(db_path), SqliteProblemRepository(db_path), executor
    )

    evaluation = await service.evaluate(problem_id, "local-user", Language.PYTHON, code)

    assert evaluation.passed_tests == 1
    assert evaluation.total_tests == 1


async def test_evaluate_grades_a_failing_submission(db_path: str) -> None:
    problem_id = await _seed_problem(db_path)
    code = "print(sum(int(x) for x in input().split()))"

    executor = FakeCodeExecutor(
        [TestResult(id="t1", status=ExecutionStatus.FAILED, input="1 2 3", actual_output="7")]
    )
    service = EvaluationService(
        SqliteEvaluationRepository(db_path), SqliteProblemRepository(db_path), executor
    )

    evaluation = await service.evaluate(problem_id, "local-user", Language.PYTHON, code)

    assert evaluation.passed_tests == 0


async def test_evaluate_returns_per_test_results_for_debugging(db_path: str) -> None:
    problem_id = await _seed_problem(db_path)
    code = "print(sum(int(x) for x in input().split()) + 1)"  # off by one

    executor = FakeCodeExecutor(
        [TestResult(id="t1", status=ExecutionStatus.FAILED, input="1 2 3", actual_output="7")]
    )
    service = EvaluationService(
        SqliteEvaluationRepository(db_path), SqliteProblemRepository(db_path), executor
    )

    evaluation = await service.evaluate(problem_id, "local-user", Language.PYTHON, code)

    assert len(evaluation.results) == 1
    assert evaluation.results[0].input == "1 2 3"
    assert evaluation.results[0].actual_output == "7"
    assert evaluation.results[0].status == ExecutionStatus.FAILED


async def test_evaluate_computes_peak_memory_across_results(db_path: str) -> None:
    problem_id = await _seed_problem(db_path)
    executor = FakeCodeExecutor(
        [TestResult(id="t1", status=ExecutionStatus.PASSED, input="1 2 3", actual_output="6", memory_kb=8192)]
    )
    service = EvaluationService(
        SqliteEvaluationRepository(db_path), SqliteProblemRepository(db_path), executor
    )

    evaluation = await service.evaluate(
        problem_id, "local-user", Language.PYTHON, "print(sum(int(x) for x in input().split()))"
    )

    assert evaluation.memory_mb == 8.0


_PASSING = [TestResult(id="t2", status=ExecutionStatus.PASSED, input="1 2 3", actual_output="6")]
_CODE = "print(sum(int(x) for x in input().split()))"


async def test_attempt_metrics_are_persisted(db_path: str) -> None:
    problem_id = await _seed_problem(db_path)
    service = EvaluationService(
        SqliteEvaluationRepository(db_path),
        SqliteProblemRepository(db_path),
        FakeCodeExecutor(_PASSING),
    )

    await service.evaluate(
        problem_id, "local-user", Language.PYTHON, _CODE,
        metrics=AttemptMetrics(duration_ms=90_000, run_count=4, hints_used=2, helper_used=True),
    )

    import sqlite3

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT duration_ms, run_count, hints_used, helper_used FROM submissions"
    ).fetchone()
    conn.close()
    assert row == (90_000, 4, 2, 1)


def test_assistance_scales_with_how_much_help_was_taken() -> None:
    assert AttemptMetrics().assistance() == 0.0
    assert AttemptMetrics(hints_used=1).assistance() == pytest.approx(0.2)
    assert AttemptMetrics(hints_used=3, helper_used=True).assistance() == pytest.approx(1.0)
    # Capped, not unbounded.
    assert AttemptMetrics(hints_used=99, helper_used=True).assistance() == 1.0
