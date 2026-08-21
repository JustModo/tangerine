from pydantic import BaseModel, Field


class LessonNoteStep(BaseModel):
    title: str = Field(description="2-5 words, plain English.")
    body_md: str = Field(
        description="GitHub-flavoured markdown, under 100 words excluding code blocks. "
        "No heading inside the body — the title is the heading."
    )


class GeneratedLessonNotes(BaseModel):
    steps: list[LessonNoteStep] = Field(
        description="2-4 steps, split only where the concept genuinely changes."
    )
