import sqlite3
from pathlib import Path

import pytest

from app.execution.domain.models import ExecutionStatus, TestResult
from app.llm.schemas.problem import GeneratedExample, GeneratedProblem, ProblemPatch
from app.problems.application.repair import apply_patch
from app.problems.application.validation import ProblemValidationService
from app.problems.domain.models import ProblemStatus
from app.problems.infrastructure.sqlite_repository import SqliteProblemRepository
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.shared.database import MIGRATIONS_DIR
from app.shared.hashing import hash_output
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


def _rows_for_skill(db_path: str, skill_id: str) -> list[tuple[str, str]]:
    """(id, status) for every problem on a skill, INVALID ones included. Read straight from
    SQL because no production query returns rejected rows — that is the point of them."""
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT p.id, p.status FROM problems p "
        "JOIN problem_skills ps ON ps.problem_id = p.id WHERE ps.skill_id = ?",
        (skill_id,),
    ).fetchall()
    conn.close()
    return rows


def _passing_results() -> list[TestResult]:
    """1 example + 3 hidden tests, all matching the reference for _generated_problem()."""
    return [
        TestResult(id="0", status=ExecutionStatus.PASSED, input="1 2 3", actual_output="6\n"),
        TestResult(id="1", status=ExecutionStatus.PASSED, input="0", actual_output="0\n"),
        TestResult(id="2", status=ExecutionStatus.PASSED, input="5", actual_output="5\n"),
        TestResult(id="3", status=ExecutionStatus.PASSED, input="-1 -2", actual_output="-3\n"),
    ]


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
        input_format="nums: list[int], the array to sum.",
        output_format="Return the sum as an int; printed on one line.",
        hints=["Consider a running total."],
        tags=["prefix-sum", "arrays"],
    )


def test_apply_patch_keeps_examples_as_model_instances() -> None:
    generated = _generated_problem()
    patch = ProblemPatch(examples=[GeneratedExample(input="1 2 3", output="7")])

    patched = apply_patch(generated, patch, source_problem=None)

    assert patched.examples[0].output == "7"
    assert isinstance(patched.examples[0], GeneratedExample)


async def test_generate_and_validate_marks_available_on_success(db_path: str) -> None:
    repo = SqliteProblemRepository(db_path)
    llm = FakeLLMProvider(structured_responses=[_generated_problem()])
    # 4 results: 1 example + 3 hidden tests.
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
    # Tests: examples + hidden inputs (learner can't hardcode if hidden aren't included).
    assert len(version.tests) == 4
    assert len(version.examples) == 1
    assert [t.input for t in version.tests] == ["1 2 3", "0", "5", "-1 -2"]
    # Hashes from executor output, not LLM.
    assert version.tests[0].output_hash == hash_output("6\n")
    assert version.tests[3].output_hash == hash_output("-3\n")
    assert version.constraints == "1 <= len(nums) <= 10^5"
    assert version.hints == ["Consider a running total."]
    assert problem.tags == ["prefix-sum", "arrays"]
    # Persisted user_code is the stub, not the reference.
    assert version.user_code == "def solve(nums): pass"
    assert version.pre_code == "nums = list(map(int, input().split()))"
    assert version.post_code == "print(solve(nums))"


async def test_generate_and_validate_marks_invalid_when_reference_solution_errors(db_path: str) -> None:
    repo = SqliteProblemRepository(db_path)
    # Generate -> reject -> repair -> reject -> regenerate -> reject, then give up.
    llm = FakeLLMProvider(
        structured_responses=[
            _generated_problem(),
            ProblemPatch(reference_user_code="def solve(nums): return sum(nums)"),
            _generated_problem(),
        ]
    )
    executor = FakeCodeExecutor(
        [TestResult(id="0", status=ExecutionStatus.ERROR, input="1 2 3", error="boom")]
    )
    service = ProblemValidationService(repo, llm, executor, SqliteSkillRepository(db_path))

    problem = await service.generate_and_validate("prefix-sum", Language.PYTHON, "easy")

    assert problem is None
    rows = _rows_for_skill(db_path, await SqliteSkillRepository(db_path).ensure_skill("prefix-sum"))
    assert len(rows) == 3  # one row per attempt: generate, patch, regenerate
    assert {status for _, status in rows} == {ProblemStatus.INVALID.value}


async def test_generate_and_validate_marks_invalid_when_reference_solution_prints_nothing(
    db_path: str,
) -> None:
    # Empty output is broken (any empty user submission would pass).
    repo = SqliteProblemRepository(db_path)
    llm = FakeLLMProvider(
        structured_responses=[
            _generated_problem(),
            ProblemPatch(post_code="print(solve(nums))"),
            _generated_problem(),
        ]
    )
    executor = FakeCodeExecutor(
        [TestResult(id="0", status=ExecutionStatus.PASSED, input="1 2 3", actual_output="")]
    )
    service = ProblemValidationService(repo, llm, executor, SqliteSkillRepository(db_path))

    problem = await service.generate_and_validate("prefix-sum", Language.PYTHON, "easy")

    assert problem is None
    rows = _rows_for_skill(db_path, await SqliteSkillRepository(db_path).ensure_skill("prefix-sum"))
    assert rows[0][1] == ProblemStatus.INVALID.value


async def test_reference_disagreeing_with_a_stated_example_is_rejected(db_path: str) -> None:
    # Reference must match statement examples.
    repo = SqliteProblemRepository(db_path)
    llm = FakeLLMProvider(
        structured_responses=[
            _generated_problem(),
            # Repair still disagrees with example.
            ProblemPatch(reference_user_code="def solve(nums): return sum(nums) + 1"),
            _generated_problem(),
        ]
    )
    executor = FakeCodeExecutor(
        [
            # Reference says 7, statement says 6.
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

    # One queued response, not two: a duplicate is served from the bank, so the regeneration
    # that used to run before falling back to this same row never happens.
    second = await ProblemValidationService(
        repo,
        FakeLLMProvider(structured_responses=[_generated_problem()]),
        FakeCodeExecutor(passing),
        skill_repo,
    ).generate_and_validate("prefix-sum", Language.PYTHON, "easy")

    assert second is not None and second.id == first.id
    assert len(_rows_for_skill(db_path, await skill_repo.ensure_skill("prefix-sum"))) == 1


async def test_a_near_duplicate_title_is_served_from_the_bank(db_path: str) -> None:
    """The reported bug: one plan served "Climbing Stairs", "Min Cost Climbing Stairs" and
    "Climbing Stairs" as three separate steps. An exact title hash caught none of them."""
    repo = SqliteProblemRepository(db_path)
    skill_repo = SqliteSkillRepository(db_path)
    first = await ProblemValidationService(
        repo, FakeLLMProvider(structured_responses=[_generated_problem()]),
        FakeCodeExecutor(_passing_results()), skill_repo,
    ).generate_and_validate("prefix-sum", Language.PYTHON, "easy")
    assert first is not None

    variant = _generated_problem()
    variant.title = "Minimum Cost Static Range Sum"
    second = await ProblemValidationService(
        repo, FakeLLMProvider(structured_responses=[variant]),
        FakeCodeExecutor(_passing_results()), skill_repo,
    ).generate_and_validate("dynamic programming", Language.PYTHON, "easy")

    assert second is not None and second.id == first.id


async def test_a_problem_the_learner_has_seen_is_not_reused(db_path: str) -> None:
    repo = SqliteProblemRepository(db_path)
    skill_repo = SqliteSkillRepository(db_path)
    first = await ProblemValidationService(
        repo, FakeLLMProvider(structured_responses=[_generated_problem()]),
        FakeCodeExecutor(_passing_results()), skill_repo,
    ).generate_and_validate("prefix-sum", Language.PYTHON, "easy")
    assert first is not None

    variant = _generated_problem()
    variant.title = "Minimum Cost Static Range Sum"
    second = await ProblemValidationService(
        repo, FakeLLMProvider(structured_responses=[variant]),
        FakeCodeExecutor(_passing_results()), skill_repo,
    ).generate_and_validate(
        "prefix-sum", Language.PYTHON, "easy", exclude_problem_ids=[first.id]
    )

    assert second is not None and second.id != first.id


async def test_an_unrelated_title_is_not_treated_as_a_duplicate(db_path: str) -> None:
    repo = SqliteProblemRepository(db_path)
    skill_repo = SqliteSkillRepository(db_path)
    first = await ProblemValidationService(
        repo, FakeLLMProvider(structured_responses=[_generated_problem()]),
        FakeCodeExecutor(_passing_results()), skill_repo,
    ).generate_and_validate("prefix-sum", Language.PYTHON, "easy")
    assert first is not None

    unrelated = _generated_problem()
    unrelated.title = "Climbing Stairs"
    second = await ProblemValidationService(
        repo, FakeLLMProvider(structured_responses=[unrelated]),
        FakeCodeExecutor(_passing_results()), skill_repo,
    ).generate_and_validate("prefix-sum", Language.PYTHON, "easy")

    assert second is not None and second.id != first.id
    assert len(_rows_for_skill(db_path, await skill_repo.ensure_skill("prefix-sum"))) == 2


async def test_the_plan_scoped_avoid_list_reaches_the_prompt(db_path: str) -> None:
    """A plan passes the titles its earlier steps served; a skill-scoped list would be empty
    here and the generator would be free to repeat one."""
    repo = SqliteProblemRepository(db_path)
    llm = FakeLLMProvider(structured_responses=[_generated_problem()])
    await ProblemValidationService(
        repo, llm, FakeCodeExecutor(_passing_results()), SqliteSkillRepository(db_path)
    ).generate_and_validate(
        "prefix-sum", Language.PYTHON, "easy", avoid_titles=["Climbing Stairs"]
    )

    assert "Climbing Stairs" in llm.last_structured_request.user_prompt


async def test_a_stress_input_that_fails_leaves_the_problem_usable(db_path: str) -> None:
    repo = SqliteProblemRepository(db_path)
    generated = _generated_problem()
    generated.stress_test = "1 " * 100_000
    llm = FakeLLMProvider(structured_responses=[generated])
    # Fake executor has no timing info, stress test gets dropped.
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
    # Empty inputs cause EOFError on reference solution.
    repo = SqliteProblemRepository(db_path)
    generated = _generated_problem()
    generated.hidden_tests = ["", "5", "-1 -2"]
    llm = FakeLLMProvider(structured_responses=[generated])
    # 3 results expected (1 example + 2 non-empty hidden).
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
    # No hidden tests means learner can hardcode statement answers.
    repo = SqliteProblemRepository(db_path)

    def blank_hidden_tests():
        generated = _generated_problem()
        generated.hidden_tests = ["", "   "]
        return generated

    llm = FakeLLMProvider(
        structured_responses=[
            blank_hidden_tests(),
            ProblemPatch(hidden_tests=["", "  "]),
            blank_hidden_tests(),
        ]
    )
    executor = FakeCodeExecutor(
        [TestResult(id="0", status=ExecutionStatus.PASSED, input="1 2 3", actual_output="6\n")]
    )
    service = ProblemValidationService(repo, llm, executor, SqliteSkillRepository(db_path))

    assert await service.generate_and_validate("prefix-sum", Language.PYTHON, "easy") is None


def _passing_run() -> list[TestResult]:
    return [
        TestResult(id="0", status=ExecutionStatus.PASSED, input="1 2 3", actual_output="6\n"),
        TestResult(id="1", status=ExecutionStatus.PASSED, input="0", actual_output="0\n"),
        TestResult(id="2", status=ExecutionStatus.PASSED, input="5", actual_output="5\n"),
        TestResult(id="3", status=ExecutionStatus.PASSED, input="-1 -2", actual_output="-3\n"),
    ]


def _crashing_run() -> list[TestResult]:
    return [
        TestResult(
            id="0", status=ExecutionStatus.ERROR, input="1 2 3",
            error="TypeError: solve() takes 1 positional argument but 2 were given",
        )
    ]


async def test_a_repair_rescues_a_problem_the_first_run_rejected(db_path: str) -> None:
    # Repair loop: failure back to model, targeted fix, save (vs blind regenerate).
    repo = SqliteProblemRepository(db_path)
    llm = FakeLLMProvider(
        structured_responses=[
            _generated_problem(),
            ProblemPatch(reference_user_code="def solve(nums): return sum(nums)  # repaired"),
        ]
    )
    executor = FakeCodeExecutor(_crashing_run(), _passing_run())
    service = ProblemValidationService(repo, llm, executor, SqliteSkillRepository(db_path))
    stages: list[str] = []

    problem = await service.generate_and_validate(
        "prefix-sum", Language.PYTHON, "easy", on_stage=stages.append
    )

    assert problem is not None and problem.status == ProblemStatus.AVAILABLE
    assert stages == ["generating", "validating", "patching", "revalidating"]
    version = await repo.get_latest_version(problem.id)
    assert version is not None and "# repaired" in version.reference_solution
    # Patch only replaces named fields, rest carry over.
    assert problem.title == "Static Range Sum"
    assert [t.input for t in version.tests] == ["1 2 3", "0", "5", "-1 -2"]
    assert version.user_code == "def solve(nums): pass"


async def test_a_repair_may_not_rewrite_a_pasted_question(db_path: str) -> None:
    # Can fix harness, not the question itself.
    repo = SqliteProblemRepository(db_path)
    llm = FakeLLMProvider(
        structured_responses=[
            _generated_problem(),
            ProblemPatch(
                statement_md="A completely different question.",
                reference_user_code="def solve(nums): return sum(nums)",
            ),
        ]
    )
    executor = FakeCodeExecutor(_crashing_run(), _passing_run())
    service = ProblemValidationService(repo, llm, executor, SqliteSkillRepository(db_path))

    problem = await service.generate_and_validate(
        "prefix-sum", Language.PYTHON, "easy", source_problem="Sum the array. Please."
    )

    assert problem is not None and problem.status == ProblemStatus.AVAILABLE
    version = await repo.get_latest_version(problem.id)
    assert version is not None
    assert version.statement_md == "Given an array, answer sum queries."


async def test_a_problem_that_validates_first_time_is_never_patched(db_path: str) -> None:
    repo = SqliteProblemRepository(db_path)
    llm = FakeLLMProvider(structured_responses=[_generated_problem()])
    service = ProblemValidationService(
        repo, llm, FakeCodeExecutor(_passing_run()), SqliteSkillRepository(db_path)
    )
    stages: list[str] = []

    problem = await service.generate_and_validate(
        "prefix-sum", Language.PYTHON, "easy", on_stage=stages.append
    )

    assert problem is not None
    assert stages == ["generating", "validating"]


async def test_an_unusable_repair_falls_through_to_a_fresh_generation(db_path: str) -> None:
    # Empty patch skips revalidation, goes straight to regenerate.
    repo = SqliteProblemRepository(db_path)
    llm = FakeLLMProvider(
        structured_responses=[_generated_problem(), ProblemPatch(), _generated_problem()]
    )
    executor = FakeCodeExecutor(_crashing_run(), _passing_run())
    service = ProblemValidationService(repo, llm, executor, SqliteSkillRepository(db_path))
    stages: list[str] = []

    problem = await service.generate_and_validate(
        "prefix-sum", Language.PYTHON, "easy", on_stage=stages.append
    )

    assert stages == ["generating", "validating", "patching", "regenerating", "validating"]
    assert problem is not None and problem.status == ProblemStatus.AVAILABLE
