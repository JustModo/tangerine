from datetime import datetime

from pydantic import BaseModel

from app.execution.domain.models import TestResult


class Submission(BaseModel):
    id: str
    problem_id: str
    user_id: str
    code_snapshot: str
    created_at: datetime


class Evaluation(BaseModel):
    id: str
    submission_id: str
    passed_tests: int
    total_tests: int
    runtime_ms: float | None = None
    memory_mb: float | None = None  # peak across per-test memory_kb; null when the executor can't measure it (e.g. the local JS fallback)
    created_at: datetime
    # Per-test breakdown (input/status/actual_output) — never the expected output, since
    # problem_tests only ever stores its hash. Not persisted —
    # only returned in the direct /submit response, so it's there right when it matters
    # for debugging, without adding a table for something that's cheap to just re-run.
    results: list[TestResult] = []
