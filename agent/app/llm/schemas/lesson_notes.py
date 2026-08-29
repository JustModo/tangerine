from pydantic import BaseModel, Field


class LessonNoteStep(BaseModel):
    title: str = Field(description="2-5 words, plain English.")
    body_md: str = Field(
        description="GitHub-flavoured markdown, 40-90 words excluding code blocks. ONE IDEA "
        "PER LINE — never a paragraph, never a sentence over 15 words, never more than 3 "
        "prose lines before a code block. Alternate short prose with SMALL code blocks, "
        "each introduced by a lead-in line ending in a colon. Leave NO gap: say why the "
        "technique works, never just that it does, and ask the reader's own question out "
        "loud before answering it. Bold the one sentence worth remembering; use `inline "
        "code` for every identifier. Code blocks show the trace of changing values, and the "
        "printed output follows in its OWN fenced block."
    )


class GeneratedLessonNotes(BaseModel):
    steps: list[LessonNoteStep] = Field(
        description="3-6 steps reading in order as one lesson, covering the problem's "
        "concepts in dependency order: why each exists, the core idea, how to use it, "
        "pitfalls and cost. Every step after the first opens by naming what the previous "
        "step left unsolved."
    )
