from typing import Protocol

from app.evaluation.domain.models import Evaluation, Submission


class EvaluationRepository(Protocol):
    async def save_submission(self, submission: Submission) -> None: ...

    async def save_evaluation(self, evaluation: Evaluation) -> None: ...
