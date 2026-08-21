from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from app.shared.types import Language


class LessonNodeStatus(StrEnum):
    LOCKED = "LOCKED"
    AVAILABLE = "AVAILABLE"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"


class LessonNode(BaseModel):
    id: str
    lesson_plan_id: str
    skill_id: str
    skill_name: str | None = None  # display-only, joined from skills — not its own column
    sequence_index: int
    status: LessonNodeStatus
    # "easy" | "medium" | "hard". None falls back to suggest_difficulty()'s mastery/position
    # guess at problem-selection time.
    difficulty: str | None = None
    created_at: datetime


class LessonPlan(BaseModel):
    id: str
    session_id: str
    topic: str
    language: Language
    level: str
    version: int
    created_at: datetime
    nodes: list[LessonNode] = []
