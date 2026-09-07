from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from app.shared.types import Language


class ProblemStatus(StrEnum):
    GENERATED = "GENERATED"
    VALIDATING = "VALIDATING"
    AVAILABLE = "AVAILABLE"
    INVALID = "INVALID"


class ProblemExample(BaseModel):
    id: str
    input: str
    output: str
    explanation: str | None = None


class ProblemTest(BaseModel):
    id: str
    input: str
    output_hash: str


class Problem(BaseModel):
    id: str
    title: str
    language: Language
    difficulty: str
    status: ProblemStatus
    statement_md: str = ""
    # reference_solution holds the fully assembled reference program (pre_code +
    # reference_user_code + post_code) — audit-only, never re-executed after validation.
    reference_solution: str = ""
    # Hidden harness, never sent to the frontend — concatenated with user_code at
    # Run/Submit time (app/shared/code_assembly.py) before execution.
    pre_code: str = ""
    post_code: str = ""
    # The ONLY code a learner ever sees or edits — just their function or class, not a
    # standalone runnable script.
    user_code: str = ""
    constraints: str | None = None
    input_format: str | None = None
    output_format: str | None = None
    hints: list[str] = []
    examples: list[ProblemExample] = []
    tests: list[ProblemTest] = []
    skill_ids: list[str] = []
    tags: list[str] = []
    created_at: datetime


class ProblemVersion(BaseModel):
    """Backwards-compatible view of problem content."""
    id: str
    problem_id: str
    version: int = 1
    statement_md: str = ""
    reference_solution: str = ""
    pre_code: str = ""
    post_code: str = ""
    user_code: str = ""
    constraints: str | None = None
    input_format: str | None = None
    output_format: str | None = None
    hints: list[str] = []
    examples: list[ProblemExample] = []
    tests: list[ProblemTest] = []
    created_at: datetime | None = None


class ProblemCriteria(BaseModel):
    skill_id: str | None = None
    language: Language | None = None
    difficulty: str | None = None
    exclude_problem_ids: list[str] = []
