from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from app.shared.types import Language


class ProblemStatus(StrEnum):
    GENERATED = "GENERATED"
    VALIDATING = "VALIDATING"
    VALID = "VALID"
    AVAILABLE = "AVAILABLE"
    INVALID = "INVALID"


class Skill(BaseModel):
    id: str
    name: str
    description: str | None = None


class ProblemExample(BaseModel):
    id: str
    input: str
    output: str
    explanation: str | None = None


class ProblemTest(BaseModel):
    id: str
    input: str
    output_hash: str
    is_hidden: bool = True


class ProblemVersion(BaseModel):
    id: str
    problem_id: str
    version: int
    statement_md: str
    # reference_solution holds the fully assembled reference program (pre_code +
    # reference_user_code + post_code) — audit-only, never re-executed after validation.
    reference_solution: str
    # Hidden harness, never sent to the frontend — concatenated with user_code at
    # Run/Submit time (app/shared/code_assembly.py) before execution.
    pre_code: str = ""
    post_code: str = ""
    # The ONLY code a learner ever sees or edits — just their function/class (was
    # `boilerplate`, renamed since it's no longer a standalone runnable script).
    user_code: str = ""
    constraints: str | None = None
    hints: list[str] = []
    examples: list[ProblemExample] = []
    tests: list[ProblemTest] = []
    created_at: datetime


class Problem(BaseModel):
    id: str
    conceptual_id: str
    title: str
    language: Language
    difficulty: str
    status: ProblemStatus
    skill_ids: list[str] = []
    tags: list[str] = []
    created_at: datetime


class ProblemCriteria(BaseModel):
    skill_id: str | None = None
    language: Language | None = None
    difficulty: str | None = None
    exclude_problem_ids: list[str] = []
