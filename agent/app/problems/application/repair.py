"""Describing a failed validation back to the model, and merging its repair back in.

Kept out of the validation service: that decides whether a problem is fit to serve, while
this decides what to tell the model and how much of it to send (see the clip limits below).
The repair path is optional to validation.
"""

from dataclasses import dataclass
from typing import Literal

from app.execution.domain.models import ExecutionStatus, TestResult
from app.llm.schemas.problem import GeneratedExample, GeneratedProblem, ProblemPatch

# How much of any one value reaches the repair prompt. A failing stdin or stdout can be a
# stress-sized blob, and the model needs its shape rather than all of it.
_CLIP = 200
_CLIP_ERROR = 300
# Two failing cases is enough to show a pattern; more just costs tokens for the same fix.
_MAX_REPORTED_CASES = 2

FailureKind = Literal["no_tests", "runtime", "mismatch"]


@dataclass(frozen=True)
class ValidationFailure:
    """Why a generated problem was rejected, small enough to send straight back to the
    model. The diagnosis already exists at the moment of rejection; keeping it is what
    separates a targeted repair from a blind retry."""

    kind: FailureKind
    detail: str


def normalise_output(value: str | None) -> str:
    """Sandbox stdout vs. a statement's example output: trailing whitespace and line
    endings differ constantly and mean nothing."""
    return "\n".join(line.rstrip() for line in (value or "").strip().splitlines())


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


def runtime_failure(results: list[TestResult], expected_count: int) -> ValidationFailure:
    """The reference solution crashed, timed out, printed nothing, or never finished."""
    if len(results) != expected_count:
        return ValidationFailure(
            "runtime",
            f"The sandbox returned {len(results)} results for {expected_count} inputs — "
            "the program did not run to completion on all of them.",
        )
    broken = [
        result
        for result in results
        if result.status in (ExecutionStatus.ERROR, ExecutionStatus.TIMEOUT)
        or not (result.actual_output or "").strip()
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
    """The reference ran fine but disagrees with an answer the statement itself claims."""
    disagreeing = [
        (example, result)
        for example, result in zip(examples, results)
        if normalise_output(result.actual_output) != normalise_output(example.output)
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
    """Merge a repair over the original. Unset fields are left alone — that asymmetry is
    exactly why a repair costs a fraction of a regeneration.

    Returns the original object unchanged (identity, not a copy) when there is nothing to
    apply, so the caller can tell a real repair from an empty one.
    """
    if patch is None:
        return generated
    # Preserve nested model instances: model_dump() serializes them to dicts.
    update = {
        name: value
        for name in patch.model_fields_set
        if (value := getattr(patch, name)) is not None
    }
    # A pasted problem is the learner's own question. Fixing the harness around it is our
    # job; rewriting what it asks is not, no matter how confidently the model offers to.
    if source_problem:
        update.pop("statement_md", None)
    return generated.model_copy(update=update) if update else generated
