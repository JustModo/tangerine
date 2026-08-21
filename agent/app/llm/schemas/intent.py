from enum import StrEnum

from pydantic import BaseModel


class UserIntent(StrEnum):
    LEARNING_PLAN = "learning_plan"
    SINGLE_PROBLEM = "single_problem"
    UNCLEAR = "unclear"


class ClassifiedIntent(BaseModel):
    intent: UserIntent
    topic: str | None = None
    clarifying_question: str | None = None
