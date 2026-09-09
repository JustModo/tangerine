from datetime import datetime

from pydantic import BaseModel

from app.execution.domain.models import TestResult


class AttemptMetrics(BaseModel):
    """Client-reported metrics about a submission attempt."""

    duration_ms: int | None = None
    run_count: int | None = None
    hints_used: int | None = None
    helper_used: bool | None = None

    def assistance(self) -> float:
        """Calculate assistance score between 0.0 (unaided) and 1.0 (assisted)."""
        score = 0.2 * min(self.hints_used or 0, 3)
        if self.helper_used:
            score += 0.4
        return min(score, 1.0)


class Submission(BaseModel):
    id: str
    problem_id: str
    user_id: str
    code_snapshot: str
    metrics: AttemptMetrics = AttemptMetrics()
    created_at: datetime


class Evaluation(BaseModel):
    id: str
    submission_id: str
    passed_tests: int
    total_tests: int
    runtime_ms: float | None = None
    memory_mb: float | None = None
    created_at: datetime
    results: list[TestResult] = []
