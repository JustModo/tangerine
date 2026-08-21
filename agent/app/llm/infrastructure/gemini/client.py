from google import genai
from google.genai import types


class GeminiClient:
    """Thin wrapper around the Gemini SDK — isolates the actual API surface so the
    rest of the app never imports google.genai directly (plan.md §49/80)."""

    def __init__(self, api_key: str | None) -> None:
        self._client = genai.Client(api_key=api_key)

    async def generate_json(
        self, *, model: str, system_prompt: str, user_prompt: str, response_schema: dict
    ) -> str:
        # A fresh chat per call, not models.generate_content — the SDK warns that direct
        # generate_content use isn't recommended for automatic function calling; we don't
        # use tools here, but a single-turn chat is the SDK's own supported shape anyway.
        chat = self._client.aio.chats.create(
            model=model,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=response_schema,
            ),
        )
        response = await chat.send_message(user_prompt)
        return response.text or ""

    async def generate_text(self, *, model: str, system_prompt: str, user_prompt: str) -> str:
        chat = self._client.aio.chats.create(
            model=model,
            config=types.GenerateContentConfig(system_instruction=system_prompt),
        )
        response = await chat.send_message(user_prompt)
        return response.text or ""
