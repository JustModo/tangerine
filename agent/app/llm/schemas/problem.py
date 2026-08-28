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
    # Hidden harness concatenated before execution; see code_assembly.py.
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
    constraints: str = Field(
        description="Input value ranges and input-size bounds, one per line (e.g. "
        "'1 <= n <= 10^5'). Never the expected time or space complexity — that names the "
        "approach, which is most of the exercise.",
    )
    input_format: str = Field(
        description="One stdin variable per line, separated by \\n, in the order pre_code "
        "(python) or post_code's main (c/cpp/java) reads it. Each line: name, type, and a "
        "concise meaning — use the SAME names as the function parameters. No prose, no "
        "blank lines.",
    )
    output_format: str = Field(
        description="Same style as input_format: one point per line, separated by \\n, "
        "concise. Cover what the function returns (type included) and what the single "
        "printed line looks like, e.g. 'Returns the list of indices.\\nPrinted "
        "space-separated on one line.'",
    )
    hints: list[str] = []
    tags: list[str] = []


class ProblemPatch(BaseModel):
    """A repair for a problem that failed sandbox validation. Only the fields that were
    actually wrong — anything left null keeps its original value.

    Narrow by design: a repair costs a fraction of a regeneration's output tokens, and
    anything not named here (title, difficulty, skills, constraints, input_format,
    output_format, hints, tags, stress_test) is untouched."""

    pre_code: str | None = Field(default=None, description="Only if the harness before the function was wrong.")
    user_code: str | None = Field(default=None, description="Only if the learner's stub no longer matches the reference signature.")
    post_code: str | None = Field(default=None, description="Only if the driver/print after the function was wrong.")
    reference_user_code: str | None = Field(default=None, description="Only if the solution itself was wrong.")
    examples: list[GeneratedExample] | None = Field(
        default=None,
        description="ALL examples in their original order, or null. Inputs must stay "
        "exactly as they were — only a stated output may be corrected.",
    )
    hidden_tests: list[str] | None = Field(
        default=None, description="Replacement grading inputs, only if the originals were unusable."
    )
    statement_md: str | None = Field(
        default=None,
        description="Only if the statement itself stated the wrong answer. Never rewrite "
        "the question being asked.",
    )
