from pydantic import BaseModel


class RevisionCandidate(BaseModel):
    skill_id: str
    skill_name: str
    reason: str
    priority: float
    mastery_score: float = 0.0
    days_since_seen: float = 0.0
