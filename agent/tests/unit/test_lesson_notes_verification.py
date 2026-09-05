"""The guards that stop a lesson being served on trust.

A lesson is the one thing here that never met a compiler: its traces are worked out in the
model's head, so these cover the two places a wrong one is caught — the schema and the
sandbox — and the promise that neither may cost the learner the lesson entirely.
"""

from functools import partial

import pytest
from pydantic import ValidationError

from app.curriculum.application.lesson_verification import traced_blocks, verify_lesson_code
from app.execution.domain.models import ExecutionStatus, TestResult
from app.llm.graphs.lesson_notes import generate_lesson_notes
from app.llm.schemas.lesson_notes import GeneratedLessonNotes, LessonNoteStep
from tests.fakes import FakeCodeExecutor, FakeLLMProvider

_PROSE = (
    "You want the running total as it grows. Print it inside the loop so every change is "
    "visible, not just the one answer waiting at the very end of the pass."
)


def _body(claimed: str) -> str:
    return f"{_PROSE}\nThe trace is:\n```python\nprint(1)\n```\nOutput:\n```\n{claimed}\n```\n"


def _notes(claimed: str = "1") -> GeneratedLessonNotes:
    return GeneratedLessonNotes(
        steps=[LessonNoteStep(title=f"Step {index}", body_md=_body(claimed)) for index in range(3)]
    )


def _ran(output: str) -> list[TestResult]:
    return [TestResult(id="0", status=ExecutionStatus.PASSED, input="", actual_output=output)]


async def _lesson(provider, executor) -> GeneratedLessonNotes:
    return await generate_lesson_notes(
        provider,
        "prefix-sum",
        "python",
        "beginner",
        verifier=partial(verify_lesson_code, executor),
    )


def test_a_lesson_too_short_to_teach_is_rejected() -> None:
    """Two steps cannot cover why a concept exists, how it works and what it costs."""
    with pytest.raises(ValidationError):
        GeneratedLessonNotes(steps=[LessonNoteStep(title="Only", body_md=_body("1"))] * 2)


def test_a_wall_of_prose_is_rejected() -> None:
    """The rule the prompt breaks most, and the one nothing used to check."""
    with pytest.raises(ValidationError):
        LessonNoteStep(title="Wall", body_md="word " * 200)


def test_a_diagram_is_not_mistaken_for_claimed_output() -> None:
    """Both sit in untagged blocks; only one is a claim about what the code prints."""
    body = f"{_PROSE}\nThe shape is:\n```python\nprint(1)\n```\nThe window:\n```\n[1, 2]\n```\n"
    assert traced_blocks(body, "python") == []
    assert traced_blocks(_body("1"), "python") == [("print(1)\n", "1\n")]


async def test_a_lesson_that_invents_its_output_is_regenerated() -> None:
    provider = FakeLLMProvider(structured_responses=[_notes("2"), _notes("1")])
    notes = await _lesson(provider, FakeCodeExecutor(_ran("1\n")))

    assert traced_blocks(notes.steps[0].body_md, "python") == [("print(1)\n", "1\n")]
    assert "does not print what its Output block claims" in provider.last_structured_request.user_prompt


async def test_an_unverifiable_lesson_still_beats_no_lesson() -> None:
    """Verification may cost a regeneration, never the lesson itself."""
    provider = FakeLLMProvider(structured_responses=[_notes("2")] * 3)
    notes = await _lesson(provider, FakeCodeExecutor(_ran("1\n")))
    assert len(notes.steps) == 3


async def test_a_snippet_that_never_ran_is_not_evidence_of_a_bad_lesson() -> None:
    """An illustrative method body cannot compile alone in c or java."""
    crashed = [TestResult(id="0", status=ExecutionStatus.ERROR, input="", error="boom")]
    assert await verify_lesson_code(FakeCodeExecutor(crashed), _notes("2"), "python") is None
