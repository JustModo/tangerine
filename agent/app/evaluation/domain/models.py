from datetime import datetime

from pydantic import BaseModel

from app.execution.domain.models import TestResult


class AttemptMetrics(BaseModel):
    """What the attempt actually cost the learner. Reported by the client — the server sees
    neither the editor clock nor which hints were revealed. All optional: an old client, or
    a submission from a context that doesn't track them, simply says nothing."""

    duration_ms: int | None = None
    run_count: int | None = None
    hints_used: int | None = None
    helper_used: bool | None = None

    def assistance(self) -> float:
        """0.0 unaided to 1.0 heavily assisted, for weighting the mastery delta. Solving
        after three hints and a conversation with the helper is not the same evidence of
        mastery as solving cold, and scoring them identically makes the whole record
        meaningless."""
        # ponytail: flat weights, no calibration. Revisit if the record starts disagreeing
        # with how learners actually perform.
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
    memory_mb: float | None = None  # peak across per-test memory_kb; null when the executor can't measure it (e.g. the local JS fallback)
    # 'optimal' | 'acceptable' | 'slow'. Null when the problem has no stress input, or the
    # submission didn't pass everything — there's nothing to grade the speed of.
    complexity_verdict: str | None = None
    created_at: datetime
    # Per-test breakdown (input/status/actual_output) — never the expected output, since
    # problem_tests only ever stores its hash. Not persisted —
    # only returned in the direct /submit response, so it's there right when it matters
    # for debugging, without adding a table for something that's cheap to just re-run.
    results: list[TestResult] = []
