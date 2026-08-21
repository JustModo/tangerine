from pydantic import BaseModel

from app.execution.domain.models import ExecutionRequest, TestResult
from app.llm.domain.requests import StructuredGenerationRequest, TextGenerationRequest


class FakeLLMProvider:
    """Test double for LLMProvider — returns/raises queued canned responses in order,
    so graph logic (retry loops, schema handling) can be tested without a live API key."""

    def __init__(self, structured_responses=None, text_responses=None) -> None:
        self._structured_responses = list(structured_responses or [])
        self._text_responses = list(text_responses or [])

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


class FakeCodeExecutor:
    """Test double for CodeExecutor — yields a fixed sequence of TestResults regardless
    of the request, so callers can be tested without a live Node sandbox."""

    def __init__(self, results: list[TestResult]) -> None:
        self._results = results

    async def execute(self, request: ExecutionRequest):
        for result in self._results:
            yield result

