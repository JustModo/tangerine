from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from app.curriculum.domain.models import LessonPlan
from app.llm.domain.requests import ChatTurn, ToolDeclaration


@dataclass(frozen=True)
class ToolContext:
    session_id: str
    args: dict
    history: list[ChatTurn]
    message: str
    active_plan: LessonPlan | None
    user_id: str | None
    depth: int
    note_id: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    tool: ToolDeclaration
    handler: Callable[..., AsyncIterator[dict]]
    available: Callable[[Any, LessonPlan | None, str | None], bool]
