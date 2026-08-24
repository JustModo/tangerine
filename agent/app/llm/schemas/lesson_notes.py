from pydantic import BaseModel, Field


class LessonNoteStep(BaseModel):
    title: str = Field(description="2-5 words, plain English.")
    body_md: str = Field(
        description="GitHub-flavoured markdown, 40-120 words excluding code blocks. One "
        "idea per line — never a dense paragraph. Each code block is followed by its real "
        "printed output. No heading inside the body — the title is the heading."
    )


class GeneratedLessonNotes(BaseModel):
    steps: list[LessonNoteStep] = Field(
        description="3-5 steps reading in order as one short lesson: why it exists, the "
        "core idea, how to use it, pitfalls and cost."
    )
