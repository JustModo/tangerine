from typing import AsyncIterator, TypeVar

from pydantic import BaseModel

from app.llm.domain.requests import ChatChunk, ChatStreamRequest, StructuredGenerationRequest, TextGenerationRequest
from app.llm.infrastructure.gemini.client import GeminiClient
from app.llm.infrastructure.gemini.mapping import parse_structured_response
from app.shared.config import get_settings

T = TypeVar("T", bound=BaseModel)


class GeminiProvider:
    """LLMProvider implementation backed by Gemini. The SDK client is constructed lazily
    on first use, not in __init__ — so building a GeminiProvider (e.g. per-request DI)
    never fails just because GEMINI_API_KEY isn't configured; only an actual generation
    call does."""

    def __init__(self, client: GeminiClient | None = None) -> None:
        self._client = client
        settings = get_settings()
        self._api_key = settings.gemini_api_key
        self._default_model = settings.llm_model

    def _get_client(self) -> GeminiClient:
        if self._client is None:
            self._client = GeminiClient(api_key=self._api_key)
        return self._client

    async def generate_structured(
        self, request: StructuredGenerationRequest, response_model: type[T]
    ) -> T:
        raw = await self._get_client().generate_json(
            model=request.model or self._default_model,
            system_prompt=request.system_prompt,
            user_prompt=request.user_prompt,
            response_schema=response_model.model_json_schema(),
        )
        return parse_structured_response(raw, response_model)  # type: ignore[return-value]

    async def generate_text(self, request: TextGenerationRequest) -> str:
        return await self._get_client().generate_text(
            model=request.model or self._default_model,
            system_prompt=request.system_prompt,
            user_prompt=request.user_prompt,
        )

    async def stream_chat(self, request: ChatStreamRequest) -> AsyncIterator[ChatChunk]:
        async for chunk in self._get_client().stream_chat(
            model=request.model or self._default_model,
            system_prompt=request.system_prompt,
            history=request.history,
            message=request.message,
            tools=request.tools,
        ):
            yield chunk
