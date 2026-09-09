"""Validation failure formatting and patch application for problem generation."""

from dataclasses import dataclass
from typing import Literal

from app.execution.domain.models import ExecutionStatus, TestResult
from app.llm.schemas.problem import GeneratedExample, GeneratedProblem, ProblemPatch
from app.shared.hashing import comparable_output

_CLIP = 200
_CLIP_ERROR = 300
_CLIP_COMPILE = 1500
_MAX_REPORTED_CASES = 2

FailureKind = Literal["no_tests", "runtime", "mismatch", "compile"]


@dataclass(frozen=True)
class ValidationFailure:
    """Reason for generated problem rejection."""

    kind: FailureKind
    detail: str


def _clip(value: str | None, limit: int = _CLIP) -> str:
    text = (value or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def no_tests_failure(examples: list, hidden_tests: list[str]) -> ValidationFailure:
    return ValidationFailure(
        "no_tests",
        f"{len(examples)} usable example input(s) and {len(hidden_tests)} usable hidden "
        "test input(s) survived — blank inputs were discarded. At least one of each is "
        "required.",
    )


def execution_failure(
    results: list[TestResult], expected_count: int, all_empty: bool = False
) -> ValidationFailure:
    """Classify execution failures from reference solution run."""
    if any(result.compile_failed for result in results):
        error = next((result.error for result in results if result.error), None)
        return ValidationFailure(
            "compile",
            _clip(error or "The compiler rejected the program.", _CLIP_COMPILE),
        )
    if len(results) != expected_count:
        return ValidationFailure(
            "runtime",
            f"The sandbox returned {len(results)} results for {expected_count} inputs — "
            "the program did not run to completion on all of them.",
        )
    if all_empty:
        return ValidationFailure(
            "runtime",
            f"The reference ran without crashing on all {expected_count} inputs and printed "
            "NOTHING on every one of them. Printing a blank line for a no-answer case is "
            "fine, but blank on every input means the program never printed a real answer: "
            "post_code does not print, or pre_code consumed the wrong tokens so the "
            "function never received its arguments. Fix the harness, not the algorithm.",
        )
    broken = [
        result
        for result in results
        if result.status in (ExecutionStatus.ERROR, ExecutionStatus.TIMEOUT)
    ]
    return ValidationFailure(
        "runtime",
        "\n".join(
            f"- input={_clip(result.input)!r} status={result.status.value} "
            f"stdout={_clip(result.actual_output)!r} stderr={_clip(result.error, _CLIP_ERROR)!r}"
            for result in broken[:_MAX_REPORTED_CASES]
        ),
    )


def mismatch_failure(
    examples: list[GeneratedExample], results: list[TestResult]
) -> ValidationFailure:
    """Format mismatch between reference solution output and example output."""
    disagreeing = [
        (example, result)
        for example, result in zip(examples, results, strict=False)
        if comparable_output(result.actual_output) != comparable_output(example.output)
    ]
    return ValidationFailure(
        "mismatch",
        "\n".join(
            f"- input={_clip(example.input)!r} statement_says={_clip(example.output)!r} "
            f"reference_printed={_clip(result.actual_output)!r}"
            for example, result in disagreeing[:_MAX_REPORTED_CASES]
        ),
    )


def apply_patch(
    generated: GeneratedProblem, patch: ProblemPatch | None, source_problem: str | None
) -> GeneratedProblem:
    """Merge patch fields into generated problem."""
    if patch is None:
        return generated
    update = {
        name: value
        for name in patch.model_fields_set
        if (value := getattr(patch, name)) is not None
    }
    if source_problem:
        update.pop("statement_md", None)
    return generated.model_copy(update=update) if update else generated
