from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

from app.curriculum.domain.models import LessonPlan
from app.llm.domain.requests import ChatTurn, ToolDeclaration


@dataclass(frozen=True)
class ToolCallContext:
    session_id: str
    args: dict[str, Any]
    history: list[ChatTurn]
    message: str
    active_plan: LessonPlan | None
    user_id: str | None
    depth: int


@dataclass(frozen=True)
class ToolLabel:
    """Progress label yielded before the work it describes. Persisted ones become a system
    message the follow-up reply then overwrites; ephemeral ones are stream-only."""

    text: str
    persist: bool = False


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    summary: str
    fallback: str
    plan_id: str | None = None
    active_plan: LessonPlan | None = None
    memo: str | None = None
    instruction: str | None = None


class ChatTool(Protocol):
    """A tool the chat model can call: it yields progress labels as it works, then exactly
    one ToolResult the follow-up turn is built from."""

    @property
    def declaration(self) -> ToolDeclaration: ...

    def is_available(self, plan: LessonPlan | None, user_id: str | None) -> bool: ...

    def execute(self, ctx: ToolCallContext) -> AsyncIterator[ToolLabel | ToolResult]: ...
