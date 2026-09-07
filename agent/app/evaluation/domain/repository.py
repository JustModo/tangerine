from typing import Protocol

from app.evaluation.domain.models import Evaluation, Submission


class EvaluationRepository(Protocol):
    async def save(self, submission: Submission, evaluation: Evaluation) -> None: ...
