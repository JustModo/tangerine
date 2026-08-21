from typing import Literal

from pydantic import BaseModel, Field


class RevisedStep(BaseModel):
    title: str
    skill: str = Field(
        description="Copied character-for-character from the current plan unless this "
        "specific step is the one being changed."
    )
    difficulty: Literal["easy", "medium", "hard"] = Field(
        description="Copied exactly from the current plan unless this step's difficulty is "
        "what the instruction asks to change."
    )


class RevisedCurriculum(BaseModel):
    """Deliberately separate from GeneratedCurriculum, which the curriculum graph caches:
    this one speaks the same easy/medium/hard vocabulary the plan already stores, so a step
    the learner didn't ask to change round-trips byte-identically instead of being
    re-derived through a lossy 1-5 rating."""

    steps: list[RevisedStep]
