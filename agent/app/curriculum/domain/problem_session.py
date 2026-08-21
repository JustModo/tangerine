from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class ProblemSessionStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    COMPLETED = "COMPLETED"


class ProblemSession(BaseModel):
    """Ties a lesson node's attempt to a selected/generated problem and the user's local
    source file (plan.md §68)."""

    id: str
    lesson_node_id: str
    lesson_plan_id: str | None = None  # nullable only for rows created before this field existed
    problem_id: str
    user_id: str
    source_code: str | None = None
    status: ProblemSessionStatus
    created_at: datetime
    updated_at: datetime
