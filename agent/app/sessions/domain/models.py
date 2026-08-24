from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class SessionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class ChatRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatMessage(BaseModel):
    id: str
    session_id: str
    role: ChatRole
    content: str
    # Hidden context the model carries forward but the user never sees — chiefly the ids a
    # lookup tool returned, so a follow-up "yes" can act on them instead of re-deriving
    # them. Never rendered by the UI.
    intent: str | None = None
    created_at: datetime


class LearningSession(BaseModel):
    id: str
    user_id: str
    status: SessionStatus
    created_at: datetime
    updated_at: datetime
    messages: list[ChatMessage] = []
