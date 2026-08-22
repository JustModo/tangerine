from typing import Literal

from pydantic import BaseModel, Field


class RevisedStep(BaseModel):
    # As in GeneratedCurriculumNode, `skill` IS the step's name in the UI, and it is also
    # the key the reconciler matches on to preserve completed progress. There is no
    # separate title: one existed, was never read, and only invited the model to spend
    # tokens on it.
    skill: str = Field(
        description="Copied character-for-character from the current plan unless this "
        "specific step is the one being changed. For a NEW step, a short 2-4 word "
        "lowercase name, distinct from every other step in the plan."
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
