from typing import Literal

from pydantic import BaseModel


class StructuredGenerationRequest(BaseModel):
    system_prompt: str
    user_prompt: str
    model: str | None = None  # falls back to Settings.llm_model when unset


class ToolDeclaration(BaseModel):
    name: str
    description: str
    parameters_schema: dict


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatStreamRequest(BaseModel):
    system_prompt: str
    history: list[ChatTurn] = []
    message: str
    tools: list[ToolDeclaration] = []
    model: str | None = None


class ToolCallResult(BaseModel):
    name: str
    args: dict


class ChatChunk(BaseModel):
    text_delta: str | None = None
    tool_call: ToolCallResult | None = None
    done: bool = False
