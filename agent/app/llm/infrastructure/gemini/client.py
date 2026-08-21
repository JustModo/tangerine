from typing import AsyncIterator

from google import genai
from google.genai import types

from app.llm.domain.requests import ChatChunk, ChatTurn, ToolCallResult, ToolDeclaration


class GeminiClient:
    """Thin wrapper around the Gemini SDK — isolates the actual API surface so the
    rest of the app never imports google.genai directly."""

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

    async def stream_chat(
        self,
        *,
        model: str,
        system_prompt: str,
        history: list[ChatTurn],
        message: str,
        tools: list[ToolDeclaration],
    ) -> AsyncIterator[ChatChunk]:
        # Passing declarative types.Tool objects (not raw Python callables) means the
        # SDK's automatic function calling never has anything callable to invoke — it
        # streams a `function_call` part back to us instead, which is exactly the manual
        # handoff we want (see google.genai._extra_utils.get_function_map: it only maps
        # entries where `callable(tool)` is true).
        genai_tools = (
            [types.Tool(function_declarations=[
                types.FunctionDeclaration(
                    name=t.name, description=t.description, parameters_json_schema=t.parameters_schema
                )
                for t in tools
            ])]
            if tools
            else None
        )
        chat = self._client.aio.chats.create(
            model=model,
            history=[
                types.Content(
                    role="model" if turn.role == "assistant" else "user",
                    parts=[types.Part(text=turn.content)],
                )
                for turn in history
            ],
            config=types.GenerateContentConfig(system_instruction=system_prompt, tools=genai_tools),
        )
        async for chunk in await chat.send_message_stream(message):
            if not chunk.candidates or not chunk.candidates[0].content:
                continue
            for part in chunk.candidates[0].content.parts or []:
                if getattr(part, "function_call", None) is not None:
                    yield ChatChunk(
                        tool_call=ToolCallResult(
                            name=part.function_call.name, args=dict(part.function_call.args or {})
                        )
                    )
                elif getattr(part, "text", None):
                    yield ChatChunk(text_delta=part.text)
        yield ChatChunk(done=True)
