from typing import AsyncIterator, TypeVar

from pydantic import BaseModel

from app.llm.domain.requests import ChatChunk, ChatStreamRequest, StructuredGenerationRequest
from app.llm.infrastructure.gemini.client import GeminiClient
from app.llm.infrastructure.gemini.mapping import parse_structured_response
from app.llm.infrastructure.gemini.retry import (
    MAX_ATTEMPTS,
    backoff_delay,
    is_retryable,
    with_retry,
)
from app.shared.config import get_settings
from app.shared.secrets import get_gemini_api_key

T = TypeVar("T", bound=BaseModel)


class GeminiProvider:
    """LLMProvider implementation backed by Gemini. The SDK client is constructed lazily
    on first use, not in __init__ — so building a GeminiProvider (e.g. per-request DI)
    never fails just because GEMINI_API_KEY isn't configured; only an actual generation
    call does."""

    def __init__(self, client: GeminiClient | None = None) -> None:
        self._client = client
        self._default_model = get_settings().llm_model

    async def _get_client(self) -> GeminiClient:
        if self._client is None:
            # Resolved here rather than in __init__ so a key saved through the setup screen
            # is picked up by the next request without restarting the process.
            self._client = GeminiClient(api_key=await get_gemini_api_key())
        return self._client

    async def generate_structured(
        self, request: StructuredGenerationRequest, response_model: type[T]
    ) -> T:
        client = await self._get_client()
        raw = await with_retry(
            lambda: client.generate_json(
                model=request.model or self._default_model,
                system_prompt=request.system_prompt,
                user_prompt=request.user_prompt,
                response_schema=response_model.model_json_schema(),
            ),
            "generate_json",
        )
        return parse_structured_response(raw, response_model)  # type: ignore[return-value]

    async def stream_chat(self, request: ChatStreamRequest) -> AsyncIterator[ChatChunk]:
        """Retries only while nothing has been emitted yet. A rate limit or an overloaded
        backend rejects the request before the first token, which is the case worth
        retrying; once text is out, restarting would repeat it to the user."""
        client = await self._get_client()
        for attempt in range(MAX_ATTEMPTS):
            started = False
            try:
                async for chunk in client.stream_chat(
                    model=request.model or self._default_model,
                    system_prompt=request.system_prompt,
                    history=request.history,
                    message=request.message,
                    tools=request.tools,
                ):
                    started = True
                    yield chunk
                return
            except Exception as exc:
                if started or not is_retryable(exc) or attempt == MAX_ATTEMPTS - 1:
                    raise
                await backoff_delay(attempt, exc, "stream_chat")
