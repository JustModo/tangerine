from pydantic import BaseModel

from app.execution.domain.models import ExecutionRequest, TestResult
from app.llm.domain.requests import ChatStreamRequest, StructuredGenerationRequest
from app.llm.schemas.lesson_notes import MIN_STEPS, GeneratedLessonNotes, LessonNoteStep

_LESSON_PROSE = (
    "You want the running total as it grows, so print it inside the loop where every "
    "change is visible instead of waiting for the one answer at the end."
)


def fake_lesson_notes(first_title: str) -> GeneratedLessonNotes:
    """Notes that satisfy the schema's own step count and prose budget, so a test asserting
    on the lesson it queued is not really asserting on the fixture being long enough."""
    titles = [first_title] + [f"Then this {index}" for index in range(MIN_STEPS - 1)]
    return GeneratedLessonNotes(
        steps=[LessonNoteStep(title=title, body_md=_LESSON_PROSE) for title in titles]
    )


class FakeLLMProvider:
    """Test double for LLMProvider — returns/raises queued canned responses in order,
    so graph logic (retry loops, schema handling) can be tested without a live API key."""

    def __init__(self, structured_responses=None, chat_streams=None) -> None:
        self._structured_responses = list(structured_responses or [])
        # Each item is a list[ChatChunk] (one queued call to stream_chat()).
        self._chat_streams = list(chat_streams or [])
        # Captured for test assertions on prompt content.
        self.last_chat_request: ChatStreamRequest | None = None
        self.last_structured_request: StructuredGenerationRequest | None = None

    async def generate_structured(
        self, request: StructuredGenerationRequest, response_model: type[BaseModel]
    ) -> BaseModel:
        self.last_structured_request = request
        if not self._structured_responses:
            raise AssertionError("FakeLLMProvider: no more structured responses queued")
        next_item = self._structured_responses.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item

    async def stream_chat(self, request: ChatStreamRequest):
        self.last_chat_request = request
        if not self._chat_streams:
            raise AssertionError("FakeLLMProvider: no more chat streams queued")
        chunks = self._chat_streams.pop(0)
        for chunk in chunks:
            yield chunk


class FakeCodeExecutor:
    """Test double for CodeExecutor — yields a fixed sequence of TestResults regardless
    of the request, so callers can be tested without a live Node sandbox.

    Extra positional lists are handed to successive execute() calls, and the last one
    repeats for good: a problem that fails validation, gets repaired and is validated again
    has to see a different sandbox result the second time round."""

    def __init__(self, results: list[TestResult], *later_runs: list[TestResult]) -> None:
        self._runs = [results, *later_runs]

    async def execute(self, request: ExecutionRequest):
        results = self._runs.pop(0) if len(self._runs) > 1 else self._runs[0]
        for result in results:
            yield result

