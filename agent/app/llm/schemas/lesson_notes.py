from pydantic import BaseModel, Field, field_validator

from app.shared.markdown import prose_only

MIN_STEPS = 3
MAX_STEPS = 6
# Deliberately wider than the 40-90 words the prompt asks for: this is the backstop that
# catches an empty step or a wall of text, not the target. Every rejection here costs a
# whole regeneration, so it only fires on prose no editing pass would let through.
MIN_PROSE_WORDS = 20
MAX_PROSE_WORDS = 150


class LessonNoteStep(BaseModel):
    title: str = Field(max_length=60, description="2-5 words, plain English.")
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

    @field_validator("body_md")
    @classmethod
    def _within_prose_budget(cls, value: str) -> str:
        words = len(prose_only(value).split())
        if not MIN_PROSE_WORDS <= words <= MAX_PROSE_WORDS:
            raise ValueError(
                f"body_md has {words} words of prose excluding code blocks; it must be "
                f"between {MIN_PROSE_WORDS} and {MAX_PROSE_WORDS}, ideally 40-90"
            )
        return value


class GeneratedLessonNotes(BaseModel):
    steps: list[LessonNoteStep] = Field(
        min_length=MIN_STEPS,
        max_length=MAX_STEPS,
        description="3-6 steps reading in order as one lesson, covering the problem's "
        "concepts in dependency order: why each exists, the core idea, how to use it, "
        "pitfalls and cost. Every step after the first opens by naming what the previous "
        "step left unsolved.",
    )
