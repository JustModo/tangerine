import logging
import uuid
from datetime import UTC, datetime

from app.evaluation.domain.models import AttemptMetrics, Evaluation, Submission
from app.evaluation.domain.repository import EvaluationRepository
from app.execution.domain.executor import CodeExecutor
from app.execution.domain.models import ExecutionRequest, ExecutionStatus, parse_runtime_ms
from app.execution.domain.models import TestCase as ExecutionTestCase
from app.mastery.application.services import MasteryService
from app.problems.domain.repository import ProblemRepository
from app.shared.code_assembly import assemble_program
from app.shared.errors import NotFoundError
from app.shared.types import Language

logger = logging.getLogger(__name__)


class EvaluationService:
    """Service evaluating submissions against test cases and updating mastery."""

    def __init__(
        self,
        repository: EvaluationRepository,
        problem_repository: ProblemRepository,
        executor: CodeExecutor,
        mastery_service: MasteryService | None = None,
    ) -> None:
        self._repository = repository
        self._problem_repository = problem_repository
        self._executor = executor
        self._mastery_service = mastery_service

    async def evaluate(
        self,
        problem_id: str,
        user_id: str,
        language: Language,
        code: str,
        metrics: AttemptMetrics | None = None,
    ) -> Evaluation:
        problem = await self._problem_repository.get(problem_id)
        if problem is None:
            raise NotFoundError(f"Problem {problem_id} not found")

        if not problem.tests:
            raise NotFoundError(f"Problem {problem_id} has no tests to evaluate against")

        request = ExecutionRequest(
            language=language,
            code=assemble_program(problem.pre_code, code, problem.post_code),
            test_cases=[
                ExecutionTestCase(id=test.id, input=test.input, output_hash=test.output_hash)
                for test in problem.tests
            ],
        )
        results = [result async for result in self._executor.execute(request)]

        passed = sum(1 for r in results if r.status == ExecutionStatus.PASSED)
        runtimes = [t for r in results if (t := parse_runtime_ms(r.execution_time_ms)) is not None]
        runtime_ms = sum(runtimes) if runtimes else None
        memories = [r.memory_kb for r in results if r.memory_kb is not None]
        memory_mb = max(memories) / 1024 if memories else None

        metrics = metrics or AttemptMetrics()
        now = datetime.now(UTC)
        submission = Submission(
            id=str(uuid.uuid4()),
            problem_id=problem_id,
            user_id=user_id,
            code_snapshot=code,
            metrics=metrics,
            created_at=now,
        )
        passed_all = passed == len(problem.tests)

        if self._mastery_service is not None:
            assistance = metrics.assistance()
            for index, skill_id in enumerate(problem.skill_ids):
                try:
                    await self._mastery_service.record_result(
                        user_id,
                        skill_id,
                        passed_all,
                        assistance=assistance,
                        is_primary=index == 0,
                    )
                except Exception:
                    logger.warning(
                        "Mastery update failed for user %s skill %s", user_id, skill_id, exc_info=True
                    )

        evaluation = Evaluation(
            id=submission.id,
            submission_id=submission.id,
            passed_tests=passed,
            total_tests=len(problem.tests),
            runtime_ms=runtime_ms,
            memory_mb=memory_mb,
            created_at=now,
            results=results,
        )
        await self._repository.save(submission, evaluation)
        return evaluation
