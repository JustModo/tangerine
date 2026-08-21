from typing import AsyncIterator, Protocol, TypeVar

from pydantic import BaseModel

from app.llm.domain.requests import ChatChunk, ChatStreamRequest, StructuredGenerationRequest, TextGenerationRequest

T = TypeVar("T", bound=BaseModel)


class LLMProvider(Protocol):
    """Every LLM boundary in the app depends on this, never on a concrete SDK
    (plan.md §49/80) — LangGraph graphs call generate_structured/generate_text only."""

    async def generate_structured(
        self, request: StructuredGenerationRequest, response_model: type[T]
    ) -> T: ...

    async def generate_text(self, request: TextGenerationRequest) -> str: ...

    def stream_chat(self, request: ChatStreamRequest) -> AsyncIterator[ChatChunk]: ...
