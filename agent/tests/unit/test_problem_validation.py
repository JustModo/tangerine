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
        pre_code="nums = list(map(int, input().split()))",
        user_code="def solve(nums): pass",
        post_code="print(solve(nums))",
        reference_user_code="def solve(nums): return sum(nums)",
        examples=[GeneratedExample(input="1 2 3", output="6")],
        hidden_tests=["0", "5", "-1 -2"],
        constraints="1 <= len(nums) <= 10^5",
        hints=["Consider a running total."],
        tags=["prefix-sum", "arrays"],
    )


async def test_generate_and_validate_marks_available_on_success(db_path: str) -> None:
    repo = SqliteProblemRepository(db_path)
    llm = FakeLLMProvider(structured_responses=[_generated_problem()])
    # One result per graded input: the single example plus the three hidden test inputs.
    executor = FakeCodeExecutor(
        [
            TestResult(id="0", status=ExecutionStatus.PASSED, input="1 2 3", actual_output="6\n"),
            TestResult(id="1", status=ExecutionStatus.PASSED, input="0", actual_output="0\n"),
            TestResult(id="2", status=ExecutionStatus.PASSED, input="5", actual_output="5\n"),
            TestResult(id="3", status=ExecutionStatus.PASSED, input="-1 -2", actual_output="-3\n"),
        ]
    )
    service = ProblemValidationService(repo, llm, executor, SqliteSkillRepository(db_path))

    problem = await service.generate_and_validate("prefix-sum", Language.PYTHON, "easy")

    assert problem is not None
    assert problem.status == ProblemStatus.AVAILABLE

    version = await repo.get_latest_version(problem.id)
    assert version is not None
    # Graded on the example AND the hidden inputs — otherwise every "hidden" test would be
    # an input the learner can already read in the statement.
    assert len(version.tests) == 4
    assert len(version.examples) == 1
    assert [t.input for t in version.tests] == ["1 2 3", "0", "5", "-1 -2"]
    # ground truth hash comes from the executor's actual_output, not the LLM's claimed output
    assert version.tests[0].output_hash == hash_output("6\n")
    assert version.tests[3].output_hash == hash_output("-3\n")
    assert version.constraints == "1 <= len(nums) <= 10^5"
    assert version.hints == ["Consider a running total."]
    assert problem.tags == ["prefix-sum", "arrays"]
    # user_code persisted must be the STUB shown to learners, never the reference solution
    assert version.user_code == "def solve(nums): pass"
    assert version.pre_code == "nums = list(map(int, input().split()))"
    assert version.post_code == "print(solve(nums))"


async def test_generate_and_validate_marks_invalid_when_reference_solution_errors(db_path: str) -> None:
    repo = SqliteProblemRepository(db_path)
    # Two responses: a rejected problem is regenerated once before the service gives up.
    llm = FakeLLMProvider(structured_responses=[_generated_problem(), _generated_problem()])
    executor = FakeCodeExecutor(
        [TestResult(id="0", status=ExecutionStatus.ERROR, input="1 2 3", error="boom")]
    )
    service = ProblemValidationService(repo, llm, executor, SqliteSkillRepository(db_path))

    problem = await service.generate_and_validate("prefix-sum", Language.PYTHON, "easy")

    assert problem is None
    all_matching = await repo.list_by_skill(
        (await SqliteSkillRepository(db_path).ensure_skill("prefix-sum"))
    )
    assert len(all_matching) == 2  # one row per attempt
    assert {p.status for p in all_matching} == {ProblemStatus.INVALID}


async def test_generate_and_validate_marks_invalid_when_reference_solution_prints_nothing(
    db_path: str,
) -> None:
    # A "successful" (PASSED-status) run that produces empty stdout is just as broken as
    # an error — usually means the generated code is a bare class/function stub with no
    # stdin/stdout driver. Letting this through would hash_output("") as the expected
    # answer, so any equally-empty user submission would incorrectly pass too.
    repo = SqliteProblemRepository(db_path)
    llm = FakeLLMProvider(structured_responses=[_generated_problem(), _generated_problem()])
    executor = FakeCodeExecutor(
        [TestResult(id="0", status=ExecutionStatus.PASSED, input="1 2 3", actual_output="")]
    )
    service = ProblemValidationService(repo, llm, executor, SqliteSkillRepository(db_path))

    problem = await service.generate_and_validate("prefix-sum", Language.PYTHON, "easy")

    assert problem is None
    all_matching = await repo.list_by_skill(
        (await SqliteSkillRepository(db_path).ensure_skill("prefix-sum"))
    )
    assert all_matching[0].status == ProblemStatus.INVALID


async def test_reference_disagreeing_with_a_stated_example_is_rejected(db_path: str) -> None:
    # The reference solution DEFINES the expected answers, so if it disagrees with the
    # worked example in the statement, one of the two is wrong and nothing downstream can
    # tell which. Shipping it produces a problem where following the statement exactly
    # fails every hidden test, with no way for the learner to find out why.
    repo = SqliteProblemRepository(db_path)
    llm = FakeLLMProvider(structured_responses=[_generated_problem(), _generated_problem()])
    executor = FakeCodeExecutor(
        [
            # Statement says 1 2 3 -> 6. The reference prints 7.
            TestResult(id="0", status=ExecutionStatus.PASSED, input="1 2 3", actual_output="7\n"),
            TestResult(id="1", status=ExecutionStatus.PASSED, input="0", actual_output="0\n"),
            TestResult(id="2", status=ExecutionStatus.PASSED, input="5", actual_output="5\n"),
            TestResult(id="3", status=ExecutionStatus.PASSED, input="-1 -2", actual_output="-3\n"),
        ]
    )
    service = ProblemValidationService(repo, llm, executor, SqliteSkillRepository(db_path))

    assert await service.generate_and_validate("prefix-sum", Language.PYTHON, "easy") is None


async def test_trailing_whitespace_alone_is_not_a_disagreement(db_path: str) -> None:
    repo = SqliteProblemRepository(db_path)
    llm = FakeLLMProvider(structured_responses=[_generated_problem()])
    executor = FakeCodeExecutor(
        [
            TestResult(id="0", status=ExecutionStatus.PASSED, input="1 2 3", actual_output="  6  \n\n"),
            TestResult(id="1", status=ExecutionStatus.PASSED, input="0", actual_output="0\n"),
            TestResult(id="2", status=ExecutionStatus.PASSED, input="5", actual_output="5\n"),
            TestResult(id="3", status=ExecutionStatus.PASSED, input="-1 -2", actual_output="-3\n"),
        ]
    )
    service = ProblemValidationService(repo, llm, executor, SqliteSkillRepository(db_path))

    problem = await service.generate_and_validate("prefix-sum", Language.PYTHON, "easy")
    assert problem is not None and problem.status == ProblemStatus.AVAILABLE


async def test_a_repeat_of_an_existing_problem_is_not_stored_twice(db_path: str) -> None:
    repo = SqliteProblemRepository(db_path)
    passing = [
        TestResult(id="0", status=ExecutionStatus.PASSED, input="1 2 3", actual_output="6\n"),
        TestResult(id="1", status=ExecutionStatus.PASSED, input="0", actual_output="0\n"),
        TestResult(id="2", status=ExecutionStatus.PASSED, input="5", actual_output="5\n"),
        TestResult(id="3", status=ExecutionStatus.PASSED, input="-1 -2", actual_output="-3\n"),
    ]
    skill_repo = SqliteSkillRepository(db_path)
    first = await ProblemValidationService(
        repo, FakeLLMProvider(structured_responses=[_generated_problem()]),
        FakeCodeExecutor(passing), skill_repo,
    ).generate_and_validate("prefix-sum", Language.PYTHON, "easy")
    assert first is not None

    # The generator hands back the same problem again — same title, so same conceptual id.
    second = await ProblemValidationService(
        repo,
        FakeLLMProvider(structured_responses=[_generated_problem(), _generated_problem()]),
        FakeCodeExecutor(passing),
        skill_repo,
    ).generate_and_validate("prefix-sum", Language.PYTHON, "easy")

    # Falls back to the existing row rather than filling the bank with a near-identical one.
    assert second is not None and second.id == first.id
    assert len(await repo.list_by_skill(await skill_repo.ensure_skill("prefix-sum"))) == 1


async def test_a_stress_input_that_fails_leaves_the_problem_usable(db_path: str) -> None:
    repo = SqliteProblemRepository(db_path)
    generated = _generated_problem()
    generated.stress_test = "1 " * 100_000
    llm = FakeLLMProvider(structured_responses=[generated])
    # The fake replays the same list for the stress run too, and its first result is a
    # PASSED with no execution_time_ms — untimeable, so the feature is dropped.
    executor = FakeCodeExecutor(
        [
            TestResult(id="0", status=ExecutionStatus.PASSED, input="1 2 3", actual_output="6\n"),
            TestResult(id="1", status=ExecutionStatus.PASSED, input="0", actual_output="0\n"),
            TestResult(id="2", status=ExecutionStatus.PASSED, input="5", actual_output="5\n"),
            TestResult(id="3", status=ExecutionStatus.PASSED, input="-1 -2", actual_output="-3\n"),
        ]
    )
    service = ProblemValidationService(repo, llm, executor, SqliteSkillRepository(db_path))

    problem = await service.generate_and_validate("prefix-sum", Language.PYTHON, "easy")

    assert problem is not None and problem.status == ProblemStatus.AVAILABLE
    version = await repo.get_latest_version(problem.id)
    assert version is not None
    assert version.stress_input is None and version.stress_runtime_ms is None


async def test_a_timed_stress_run_becomes_the_speed_baseline(db_path: str) -> None:
    repo = SqliteProblemRepository(db_path)
    generated = _generated_problem()
    generated.stress_test = "9 9 9"
    llm = FakeLLMProvider(structured_responses=[generated])
    executor = FakeCodeExecutor(
        [
            TestResult(
                id="0", status=ExecutionStatus.PASSED, input="1 2 3",
                actual_output="6\n", execution_time_ms="120ms",
            ),
            TestResult(id="1", status=ExecutionStatus.PASSED, input="0", actual_output="0\n"),
            TestResult(id="2", status=ExecutionStatus.PASSED, input="5", actual_output="5\n"),
            TestResult(id="3", status=ExecutionStatus.PASSED, input="-1 -2", actual_output="-3\n"),
        ]
    )
    service = ProblemValidationService(repo, llm, executor, SqliteSkillRepository(db_path))

    problem = await service.generate_and_validate("prefix-sum", Language.PYTHON, "easy")

    version = await repo.get_latest_version(problem.id)
    assert version is not None
    assert version.stress_input == "9 9 9"
    assert version.stress_runtime_ms == pytest.approx(120.0)


async def test_an_empty_test_input_is_dropped_rather_than_killing_the_problem(db_path: str) -> None:
    # `input()` raises EOFError on empty stdin, so an empty hidden test makes the reference
    # crash on its own test case. The generator is asked for an empty-collection edge case,
    # so it produces these regularly — dropping the input costs one edge case, keeping it
    # costs the whole problem.
    repo = SqliteProblemRepository(db_path)
    generated = _generated_problem()
    generated.hidden_tests = ["", "5", "-1 -2"]
    llm = FakeLLMProvider(structured_responses=[generated])
    # Three inputs survive: the example plus the two non-empty hidden tests. A fourth result
    # would mean the empty input was still being sent.
    executor = FakeCodeExecutor(
        [
            TestResult(id="0", status=ExecutionStatus.PASSED, input="1 2 3", actual_output="6\n"),
            TestResult(id="1", status=ExecutionStatus.PASSED, input="5", actual_output="5\n"),
            TestResult(id="2", status=ExecutionStatus.PASSED, input="-1 -2", actual_output="-3\n"),
        ]
    )
    service = ProblemValidationService(repo, llm, executor, SqliteSkillRepository(db_path))

    problem = await service.generate_and_validate("prefix-sum", Language.PYTHON, "easy")

    assert problem is not None and problem.status == ProblemStatus.AVAILABLE
    version = await repo.get_latest_version(problem.id)
    assert version is not None
    assert [t.input for t in version.tests] == ["1 2 3", "5", "-1 -2"]


async def test_a_problem_with_no_usable_hidden_test_is_rejected(db_path: str) -> None:
    # Every graded input would then be one the learner can read in the statement, so
    # hardcoding the answers passes and the grade means nothing.
    repo = SqliteProblemRepository(db_path)

    def blank_hidden_tests():
        generated = _generated_problem()
        generated.hidden_tests = ["", "   "]
        return generated

    llm = FakeLLMProvider(structured_responses=[blank_hidden_tests(), blank_hidden_tests()])
    executor = FakeCodeExecutor(
        [TestResult(id="0", status=ExecutionStatus.PASSED, input="1 2 3", actual_output="6\n")]
    )
    service = ProblemValidationService(repo, llm, executor, SqliteSkillRepository(db_path))

    assert await service.generate_and_validate("prefix-sum", Language.PYTHON, "easy") is None
