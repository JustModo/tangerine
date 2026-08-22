from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class ProblemSessionStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    COMPLETED = "COMPLETED"


class ProblemSession(BaseModel):
    """Ties an attempt to a selected/generated problem and the user's local source file.

    Usually that attempt belongs to a lesson node, but a practice session — started from
    the revision queue rather than from a plan — has neither node nor plan."""

    id: str
    lesson_node_id: str | None = None
    lesson_plan_id: str | None = None
    problem_id: str
    user_id: str
    source_code: str | None = None
    status: ProblemSessionStatus
    # Learner-set "come back to this one".
    flagged: bool = False
    created_at: datetime
    updated_at: datetime
