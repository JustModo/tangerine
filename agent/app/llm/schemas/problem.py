from pydantic import BaseModel, Field


class GeneratedExample(BaseModel):
    input: str
    output: str
    explanation: str | None = Field(
        default=None,
        description="2-4 short lines separated by \\n, showing the arithmetic that turns "
        "this input into this output. Correct numbers only, no technique names.",
    )


class GeneratedProblem(BaseModel):
    title: str = Field(
        description="Names the SITUATION in 3-6 words, the way 'Trapping Rain Water' or "
        "'Gas Station Circuit' does. Never names the data structure, the algorithm or the "
        "complexity — that hands the solver the answer."
    )
    statement_md: str = Field(
        description="A competitive-programming statement, 80-180 words: the setup stated "
        "declaratively, then the rules one per sentence (a markdown bullet list when "
        "enumerating options), then exactly what to compute, then the degenerate case. "
        "Every variable in backticks using the exact user_code parameter names. No "
        "narrative, no motivation, nobody wanting anything. At least one rule must cut "
        "against the obvious approach. No hint at how to solve it."
    )
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


class ProblemCritique(BaseModel):
    violations: list[str] = Field(
        default=[],
        description="One line per defect, each naming the offending field first, e.g. "
        "'examples[1].explanation: says 3 x 4 = 14' or 'statement_md: redefines subarray "
        "mid-paragraph'. Say what is wrong and where, never how to rewrite it. Empty when "
        "the problem is publishable as it stands.",
    )
    approved: bool = Field(
        description="true only when violations is empty and the problem could be handed to "
        "a paying learner unchanged."
    )


class ProblemRevision(BaseModel):
    title: str | None = Field(default=None, description="Only if the title was flagged.")
    statement_md: str | None = Field(
        default=None,
        description="Only if the statement was flagged. Fix the flagged defect and nothing "
        "else — the task being asked stays identical.",
    )
    constraints: str | None = Field(default=None, description="Only if constraints were flagged.")
    input_format: str | None = Field(default=None, description="Only if input_format was flagged.")
    output_format: str | None = Field(default=None, description="Only if output_format was flagged.")
    hints: list[str] | None = Field(default=None, description="ALL hints in order, or null.")
    tags: list[str] | None = Field(default=None, description="ALL tags, or null.")
    examples: list[GeneratedExample] | None = Field(
        default=None,
        description="ALL examples in their original order, or null. Inputs must stay exactly "
        "as they were — only a stated output or an explanation may be corrected.",
    )
    hidden_tests: list[str] | None = Field(
        default=None, description="Replacement grading inputs, only if the originals were flagged."
    )
    pre_code: str | None = Field(default=None, description="Only if pre_code was flagged.")
    user_code: str | None = Field(default=None, description="Only if the learner's stub was flagged.")
    post_code: str | None = Field(default=None, description="Only if post_code was flagged.")
    reference_user_code: str | None = Field(
        default=None, description="Only if the reference solution was flagged."
    )


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
