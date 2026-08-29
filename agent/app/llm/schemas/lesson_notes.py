from pydantic import BaseModel, Field


class LessonNoteStep(BaseModel):
    title: str = Field(description="2-5 words, plain English.")
    body_md: str = Field(
        description="GitHub-flavoured markdown, 60-160 words excluding code blocks. Derive, "
        "do not assert: each sentence follows from the one before it. One idea per line — "
        "never a dense paragraph. Code blocks print the trace of changing values, not just "
        "the final answer, and are followed by that real output. No heading inside the "
        "body — the title is the heading."
    )


class GeneratedLessonNotes(BaseModel):
    steps: list[LessonNoteStep] = Field(
        description="3-6 steps reading in order as one lesson, covering the problem's "
        "concepts in dependency order: why each exists, the core idea, how to use it, "
        "pitfalls and cost. Every step after the first opens by naming what the previous "
        "step left unsolved."
    )
