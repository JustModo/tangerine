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
    patch_problem_user_prompt,
    patch_system_prompt,
    problem_system_prompt,
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
