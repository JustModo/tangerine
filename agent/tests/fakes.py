from pydantic import BaseModel

from app.execution.domain.models import ExecutionRequest, TestResult
from app.llm.domain.requests import ChatChunk, ChatStreamRequest, StructuredGenerationRequest, TextGenerationRequest


class FakeLLMProvider:
    """Test double for LLMProvider — returns/raises queued canned responses in order,
    so graph logic (retry loops, schema handling) can be tested without a live API key."""

    def __init__(self, structured_responses=None, text_responses=None, chat_streams=None) -> None:
        self._structured_responses = list(structured_responses or [])
        self._text_responses = list(text_responses or [])
        # Each item is a list[ChatChunk] (one queued call to stream_chat()).
        self._chat_streams = list(chat_streams or [])
        # Captured for test assertions on prompt content.
        self.last_chat_request: ChatStreamRequest | None = None

    async def generate_structured(
        self, request: StructuredGenerationRequest, response_model: type[BaseModel]
    ) -> BaseModel:
        if not self._structured_responses:
            raise AssertionError("FakeLLMProvider: no more structured responses queued")
        next_item = self._structured_responses.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item

    async def generate_text(self, request: TextGenerationRequest) -> str:
        if not self._text_responses:
            raise AssertionError("FakeLLMProvider: no more text responses queued")
        return self._text_responses.pop(0)

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

