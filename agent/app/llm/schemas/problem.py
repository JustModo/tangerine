from pydantic import BaseModel, Field


class GeneratedExample(BaseModel):
    input: str
    output: str
    explanation: str | None = Field(
        default=None,
        description="2-4 short lines separated by \\n, walking through the reasoning step "
        "by step — never one long paragraph.",
    )


class GeneratedProblem(BaseModel):
    title: str = Field(description="Concise title, 5-6 words maximum.")
    statement_md: str
    difficulty: str
    skills: list[str]
    # Hidden harness — never shown to the learner. Concatenated as
    # pre_code + user_code + post_code (or, for validation, pre_code + reference_user_code +
    # post_code) into one program before execution — see app/shared/code_assembly.py.
    pre_code: str
    user_code: str
    post_code: str
    reference_user_code: str
    examples: list[GeneratedExample]
    hidden_tests: list[str] = Field(
        default=[],
        description="3-5 EXTRA stdin inputs for grading only, in the exact same format as "
        "the examples' inputs. Must be different from the examples and should probe edge "
        "cases. No expected outputs — those come from running the reference solution.",
    )
    stress_test: str | None = Field(
        default=None,
        description="ONE extra stdin input at the top of the stated constraint range, in "
        "the same format as the examples. Used to tell an optimal solution from a "
        "brute-force one — it must be large enough that the difference in running time is "
        "obvious, while the reference solution still finishes comfortably.",
    )
    constraints: str | None = None
    hints: list[str] = []
    tags: list[str] = []
