from collections.abc import Sequence

from app.curriculum.domain.models import LessonPlan
from app.llm.domain.requests import ToolDeclaration
from app.sessions.tools.base import ChatTool


class ToolRegistry:
    def __init__(self, tools: Sequence[ChatTool]) -> None:
        self._tools: dict[str, ChatTool] = {tool.declaration.name: tool for tool in tools}

    def get(self, name: str) -> ChatTool | None:
        return self._tools.get(name)

    def declarations_for(
        self, active_plan: LessonPlan | None, user_id: str | None
    ) -> list[ToolDeclaration]:
        return [
            tool.declaration for tool in self._tools.values() if tool.is_available(active_plan, user_id)
        ]
