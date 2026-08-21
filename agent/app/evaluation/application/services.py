import logging
import uuid
from datetime import datetime, timezone

from app.evaluation.domain.models import Evaluation, Submission
from app.evaluation.domain.repository import EvaluationRepository
from app.execution.domain.executor import CodeExecutor
from app.execution.domain.models import ExecutionRequest, ExecutionStatus
from app.execution.domain.models import TestCase as ExecutionTestCase
from app.mastery.application.services import MasteryService
from app.problems.domain.repository import ProblemRepository
from app.shared.code_assembly import assemble_program
from app.shared.errors import NotFoundError
from app.shared.types import Language

logger = logging.getLogger(__name__)


def _parse_runtime_ms(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value.rstrip("ms").strip())
    except ValueError:
        return None


class EvaluationService:
    """Evaluate pipeline (plan.md §16-18): deterministic hidden-test grading, start to
    finish, with no LLM anywhere in it. Advice about a submission is the code helper
    chat's job (app/curriculum/application/code_helper.py), not this service's."""

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
        self, problem_id: str, user_id: str, language: Language, code: str
    ) -> Evaluation:
        problem = await self._problem_repository.get(problem_id)
        if problem is None:
            raise NotFoundError(f"Problem {problem_id} not found")

        version = await self._problem_repository.get_latest_version(problem_id)
        if version is None or not version.tests:
            raise NotFoundError(f"Problem {problem_id} has no tests to evaluate against")

        request = ExecutionRequest(
            language=language,
            code=assemble_program(version.pre_code, code, version.post_code),
            test_cases=[
                ExecutionTestCase(id=test.id, input=test.input, output_hash=test.output_hash)
                for test in version.tests
            ],
        )
        results = [result async for result in self._executor.execute(request)]

        passed = sum(1 for r in results if r.status == ExecutionStatus.PASSED)
        runtimes = [t for r in results if (t := _parse_runtime_ms(r.execution_time_ms)) is not None]
        runtime_ms = sum(runtimes) if runtimes else None
        memories = [r.memory_kb for r in results if r.memory_kb is not None]
        memory_mb = max(memories) / 1024 if memories else None

        now = datetime.now(timezone.utc)
        submission = Submission(
            id=str(uuid.uuid4()),
            problem_id=problem_id,
            user_id=user_id,
            code_snapshot=code,
            created_at=now,
        )
        await self._repository.save_submission(submission)

        if self._mastery_service is not None:
            passed_all = passed == len(version.tests)
            for skill_id in problem.skill_ids:
                try:
                    await self._mastery_service.record_result(user_id, skill_id, passed_all)
                except Exception:
                    logger.warning(
                        "Mastery update failed for user %s skill %s", user_id, skill_id, exc_info=True
                    )

        evaluation = Evaluation(
            id=str(uuid.uuid4()),
            submission_id=submission.id,
            passed_tests=passed,
            total_tests=len(version.tests),
            runtime_ms=runtime_ms,
            memory_mb=memory_mb,
            created_at=now,
            results=results,
        )
        await self._repository.save_evaluation(evaluation)
        return evaluation
