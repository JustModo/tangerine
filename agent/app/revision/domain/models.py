from pydantic import BaseModel


class RevisionCandidate(BaseModel):
    skill_id: str
    skill_name: str
    reason: str
    priority: float
