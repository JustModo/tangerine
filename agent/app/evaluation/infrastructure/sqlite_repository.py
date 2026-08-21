
from app.evaluation.domain.models import Evaluation, Submission
from app.shared.config import get_settings
from app.shared.database import connect


class SqliteEvaluationRepository:
    def __init__(self, database_path: str | None = None) -> None:
        self._database_path = database_path or get_settings().database_path

    async def save_submission(self, submission: Submission) -> None:
        async with connect(self._database_path) as db:
            await db.execute(
                "INSERT INTO submissions (id, problem_id, user_id, code_snapshot, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    submission.id,
                    submission.problem_id,
                    submission.user_id,
                    submission.code_snapshot,
                    submission.created_at.isoformat(),
                ),
            )
            await db.commit()

    async def save_evaluation(self, evaluation: Evaluation) -> None:
        async with connect(self._database_path) as db:
            await db.execute(
                "INSERT INTO evaluations "
                "(id, submission_id, passed_tests, total_tests, runtime_ms, memory_mb, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    evaluation.id,
                    evaluation.submission_id,
                    evaluation.passed_tests,
                    evaluation.total_tests,
                    evaluation.runtime_ms,
                    evaluation.memory_mb,
                    evaluation.created_at.isoformat(),
                ),
            )
            await db.commit()
