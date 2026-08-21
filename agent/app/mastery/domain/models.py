from datetime import datetime

from pydantic import BaseModel


class UserSkillState(BaseModel):
    user_id: str
    skill_id: str
    mastery_score: float
    streak: int
    last_seen_at: datetime
