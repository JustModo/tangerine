from pydantic import BaseModel


class CoachingFeedback(BaseModel):
    assessment: str
    focus_areas: list[str]
