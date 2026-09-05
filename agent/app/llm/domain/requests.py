from typing import Literal

from pydantic import BaseModel


class StructuredGenerationRequest(BaseModel):
    system_prompt: str
    user_prompt: str


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


class ToolCallResult(BaseModel):
    name: str
    args: dict


class ChatChunk(BaseModel):
    text_delta: str | None = None
    tool_call: ToolCallResult | None = None
    done: bool = False
