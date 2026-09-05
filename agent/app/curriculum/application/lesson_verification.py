"""Proving a lesson's code prints what the lesson claims it prints.

A generated problem has always had to survive the real sandbox before it can be served,
while lesson notes were taken on trust — and a trace worked out by hand is exactly what a
model gets subtly wrong. Same executor, same comparison, one step earlier in the day.
"""

import asyncio

from app.execution.domain.executor import CodeExecutor
from app.execution.domain.models import ExecutionRequest, ExecutionStatus, TestCase
from app.llm.schemas.lesson_notes import GeneratedLessonNotes
from app.shared.hashing import comparable_output
from app.shared.markdown import FENCE
from app.shared.types import Language

# Enough to catch a lesson that invents its output, without turning one lesson into a dozen
# sandbox round trips the learner waits on.
MAX_CHECKED_BLOCKS = 4


def traced_blocks(markdown: str, language: str) -> list[tuple[str, str]]:
    """(code, claimed output) pairs: a block tagged with the lesson's own language, followed
    by the untagged block the prompt requires its printed output to sit in.

    The lead-in between them is what tells that pair apart from a diagram or a value trace,
    which live in untagged blocks too and have nothing to run."""
    blocks = list(FENCE.finditer(markdown))
    return [
        (code.group(2), claimed.group(2))
        for code, claimed in zip(blocks, blocks[1:], strict=False)
        if code.group(1).lower() == language
        and not claimed.group(1)
        and "output" in markdown[code.end() : claimed.start()].lower()
    ]


async def _printed(executor: CodeExecutor, language: Language, code: str) -> str | None:
    """What the snippet actually printed, or None when it never ran.

    A snippet that fails to build is not proof of a bad lesson: an illustrative method body
    cannot stand alone in c or java. Skipping those beats rejecting a sound lesson."""
    request = ExecutionRequest(
        language=language,
        code=code,
        test_cases=[TestCase(id="0", input="", output_hash="")],
    )
    results = [result async for result in executor.execute(request)]
    if not results or results[0].status in (ExecutionStatus.ERROR, ExecutionStatus.TIMEOUT):
        return None
    return results[0].actual_output


async def verify_lesson_code(
    executor: CodeExecutor, notes: GeneratedLessonNotes, language: str
) -> str | None:
    """What the lesson got wrong, phrased for the model, or None if every trace holds up."""
    checks = [
        (step.title, code, claimed)
        for step in notes.steps
        for code, claimed in traced_blocks(step.body_md, language)
    ][:MAX_CHECKED_BLOCKS]
    if not checks:
        return None

    printed = await asyncio.gather(
        *(_printed(executor, Language(language), code) for _, code, _ in checks)
    )
    for (title, _, claimed), actual in zip(checks, printed, strict=True):
        if actual is None or comparable_output(actual) == comparable_output(claimed):
            continue
        return (
            f"The code in step {title!r} does not print what its Output block claims. "
            f"Running it actually prints:\n{actual.strip()}\n"
            "Fix whichever is wrong, the code or the Output block, and work every other "
            "trace in the lesson out by hand the same way."
        )
    return None
