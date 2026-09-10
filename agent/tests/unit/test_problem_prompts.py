"""The seams between the failure classifier, the prompt blocks and the assembled program.

Each of these guards a fact that is true in one file and relied on in another, which is
exactly where this used to drift.
"""

from typing import get_args

import pytest

from app.execution.domain.models import ExecutionStatus, TestResult
from app.llm.prompts.problem import (
    _DIAGNOSIS,
    _LANGUAGE_BLOCKS,
    adapt_problem_user_prompt,
    adapt_system_prompt,
    critique_system_prompt,
    critique_user_prompt,
    patch_problem_user_prompt,
    patch_system_prompt,
    problem_system_prompt,
    revise_problem_user_prompt,
    revise_system_prompt,
)
from app.llm.schemas.problem import GeneratedExample, GeneratedProblem
from app.problems.application.repair import FailureKind, execution_failure
from app.shared.code_assembly import annotated_program, assemble_program
from app.shared.types import Language


def _problem(**overrides) -> GeneratedProblem:
    defaults = {
        "title": "Sum Two Numbers",
        "statement_md": "Add them.",
        "difficulty": "easy",
        "pre_code": "a, b = map(int, input().split())",
        "user_code": "def solve(a: int, b: int) -> int:\n    return 0",
        "post_code": "print(solve(a, b))",
        "reference_user_code": "def solve(a: int, b: int) -> int:\n    return a + b",
        "constraints": "1 <= a <= 10",
        "input_format": "a: int\nb: int",
        "output_format": "the sum",
        "examples": [GeneratedExample(input="2 3", output="5")],
        "hidden_tests": ["4 5"],
        "hints": ["add"],
        "tags": ["math"],
        "skills": ["arithmetic"],
    }
    return GeneratedProblem(**{**defaults, **overrides})


def _compile_error(message: str = "Main.java:14: error: reached end of file") -> TestResult:
    return TestResult(
        id="0",
        status=ExecutionStatus.ERROR,
        input="2 3",
        error=message,
        compile_failed=True,
    )


def test_every_failure_kind_has_a_diagnosis() -> None:
    """FailureKind lives in the problems layer and _DIAGNOSIS in the llm layer; nothing but
    this stops a new kind reaching the prompt as a KeyError at repair time."""
    assert set(get_args(FailureKind)) == set(_DIAGNOSIS)


def test_every_language_has_a_prompt_block() -> None:
    assert {language.value for language in Language} == set(_LANGUAGE_BLOCKS)


@pytest.mark.parametrize("language", [language.value for language in Language])
def test_a_generation_prompt_carries_only_its_own_language(language: str) -> None:
    """The point of the split: a C generation must not pay for Python's rules."""
    prompt = problem_system_prompt(language)
    assert _LANGUAGE_BLOCKS[language] in prompt
    for other, block in _LANGUAGE_BLOCKS.items():
        if other != language:
            assert block not in prompt


def test_an_unknown_language_still_gets_a_shape_to_copy() -> None:
    """A Language added before its block is written degrades to verbose, not to silent."""
    prompt = problem_system_prompt("rust")
    assert all(block in prompt for block in _LANGUAGE_BLOCKS.values())


def test_a_compile_failure_is_not_reported_as_a_crash() -> None:
    failure = execution_failure([_compile_error(), _compile_error()], expected_count=2)
    assert failure.kind == "compile"
    # One diagnostic, not one per test case.
    assert failure.detail.count("reached end of file") == 1


def test_a_crash_is_still_a_runtime_failure() -> None:
    crashed = TestResult(id="0", status=ExecutionStatus.ERROR, input="2 3", error="boom")
    assert execution_failure([crashed], expected_count=1).kind == "runtime"


def test_a_compile_repair_is_shown_the_numbered_program_instead_of_the_fragments() -> None:
    problem = _problem()
    prompt = patch_problem_user_prompt("compile", "error: oops", "java", problem)
    assert "--- pre_code ---" in prompt
    assert "   1 | a, b = map(int, input().split())" in prompt
    # The fragments would otherwise be sent a second time, unnumbered.
    assert "post_code:\nprint(solve(a, b))" not in prompt


def test_a_mismatch_repair_is_shown_the_statement_and_the_fragments() -> None:
    prompt = patch_problem_user_prompt("mismatch", "disagrees", "python", _problem())
    assert "statement_md:\nAdd them." in prompt
    assert "--- pre_code ---" not in prompt


def test_only_a_no_tests_repair_is_shown_the_stub() -> None:
    # Anchored on the section start: "reference_user_code:" ends with the same text.
    stub = "\n\nuser_code:\n"
    assert stub in patch_problem_user_prompt("no_tests", "blank", "python", _problem())
    assert stub not in patch_problem_user_prompt("runtime", "crash", "python", _problem())


def test_patch_prompts_carry_the_language_shape() -> None:
    assert _LANGUAGE_BLOCKS["cpp"] in patch_system_prompt("cpp")


@pytest.mark.parametrize(
    "pre_code, user_code, post_code",
    [
        ("import sys", "def solve():\n    pass", "print(1)"),
        ("", "def solve():\n    pass", "print(1)"),
        ("a = 1\nb = 2", "def solve():\n    return a", "print(solve())"),
    ],
)
def test_numbered_lines_match_the_program_the_compiler_saw(
    pre_code: str, user_code: str, post_code: str
) -> None:
    """The whole value of the numbering is that `Main.java:14` lands on line 14."""
    real = assemble_program(pre_code, user_code, post_code).split("\n")
    numbered = [
        line for line in annotated_program(pre_code, user_code, post_code).split("\n")
        if not line.startswith("---")
    ]
    assert len(numbered) == len(real)
    for index, (rendered, expected) in enumerate(zip(numbered, real, strict=True), start=1):
        assert rendered == f"{index:4} | {expected}"


_SHARED_RUBRIC_SENTINELS = [
    "Never think out loud",
    "EXACTLY ONE CORRECT OUTPUT PER INPUT",
    "Do NOT state the expected time or space complexity",
    "NEVER give a completely empty input",
]


@pytest.mark.parametrize("sentinel", _SHARED_RUBRIC_SENTINELS)
def test_the_judge_grades_against_the_rules_the_generator_was_given(sentinel: str) -> None:
    """A rule inlined into one prompt instead of composed from the shared constants is a
    rubric the other side never saw, and that is exactly how a judge starts rejecting
    problems for rules the generator was never told about."""
    assert sentinel in problem_system_prompt("python")
    assert sentinel in critique_system_prompt("python")
    assert sentinel in revise_system_prompt("python")
    assert sentinel in adapt_system_prompt("python")


def test_the_critique_prompt_carries_the_evidence_it_must_judge() -> None:
    problem = _problem(
        examples=[GeneratedExample(input="2 3", output="5", explanation="2 + 3 = 5")]
    )
    prompt = critique_user_prompt(problem, None)

    assert problem.statement_md in prompt
    assert problem.examples[0].explanation in prompt
    assert problem.constraints in prompt
    assert problem.user_code in prompt
    assert problem.reference_user_code in prompt


def test_only_an_adapted_problem_shows_the_judge_the_original() -> None:
    problem = _problem()

    assert "Sum the numbers." not in critique_user_prompt(problem, None)
    assert "Sum the numbers." in critique_user_prompt(problem, "Sum the numbers.")


def test_a_revision_prompt_names_every_violation_it_must_fix() -> None:
    violations = ["statement_md: redefines subarray", "hints[0]: names the technique"]

    prompt = revise_problem_user_prompt(_problem(), violations, None)

    for violation in violations:
        assert violation in prompt


def test_a_pasted_question_is_never_put_through_the_scenario_authoring_rules() -> None:
    """The rules that make a new problem case-based would rewrite the learner's own
    question, which is the one thing adaptation must not do."""
    authoring = "WRITE A SITUATION, NOT A SPECIFICATION"

    assert authoring in problem_system_prompt("python")
    assert authoring not in adapt_system_prompt("python")
    assert "VERBATIM" in adapt_system_prompt("python")


def test_the_adapt_prompt_allows_only_markdown_repair_and_logical_fixes() -> None:
    prompt = adapt_system_prompt("python")

    assert "LOGICAL ERROR" in prompt
    assert "do NOT add a setting or a story" in prompt
    assert "Do NOT rewrite it into a scenario" in prompt


def test_the_judge_grades_a_pasted_statement_against_the_original_not_the_house_style() -> None:
    prompt = critique_user_prompt(_problem(), "Given an array, return the two indices.")

    assert "VERBATIM" in prompt
    assert "Do NOT flag statement_md for lacking a situation" in prompt
    assert "Given an array, return the two indices." in prompt


def test_the_adapt_user_prompt_carries_the_original_and_demands_it_back() -> None:
    prompt = adapt_problem_user_prompt("Return the k-th largest element.", "python")

    assert "Return the k-th largest element." in prompt
    assert "VERBATIM" in prompt


def test_a_pasted_multi_answer_question_is_normalised_in_post_code_not_in_the_statement() -> None:
    """Grading compares printed output character for character, so 'return them in any
    order' has to be reconciled somewhere. It is reconciled in the harness, not by editing
    the learner's question."""
    prompt = adapt_system_prompt("python")

    assert "SEVERAL VALID ANSWERS" in prompt
    assert "do NOT edit the statement to remove that freedom" in prompt
    assert "sort the collection before printing it" in prompt
