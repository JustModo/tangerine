from typing import AsyncIterator, Protocol, TypeVar

from pydantic import BaseModel

from app.llm.domain.requests import ChatChunk, ChatStreamRequest, StructuredGenerationRequest

T = TypeVar("T", bound=BaseModel)


class LLMProvider(Protocol):
    """Every LLM boundary in the app depends on this, never on a concrete SDK — LangGraph graphs call generate_structured only."""

    async def generate_structured(
        self, request: StructuredGenerationRequest, response_model: type[T]
    ) -> T: ...

    def stream_chat(self, request: ChatStreamRequest) -> AsyncIterator[ChatChunk]: ...
