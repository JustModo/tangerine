from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ProblemChatMessage(BaseModel):
    """One turn of the code helper conversation, scoped to a single problem session."""

    id: str
    problem_session_id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
