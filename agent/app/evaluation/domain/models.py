from datetime import datetime

from pydantic import BaseModel


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
    memory_mb: float | None = None  # runner_service.ts doesn't measure memory yet — always null for now
    complexity_verdict: str | None = None  # no static complexity analyzer built yet — always null for now
    feedback: str | None = None
    created_at: datetime
