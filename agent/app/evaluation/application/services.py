import logging
import uuid
from datetime import datetime, timezone

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


# Ratio of the learner's runtime to the reference's on the same large input. Passing every
# test says the answer is right; this says whether it would survive an interview.
# ponytail: fixed ratios and a noise floor, not a real complexity analysis — it cannot tell
# O(n log n) from O(n). Replace with a two-point curve fit (time at n and at 2n) if the
# verdict starts misleading people.
_OPTIMAL_RATIO = 2.5
_ACCEPTABLE_RATIO = 8.0
# Below this, sandbox scheduling noise swamps the signal and every ratio is meaningless.
_MIN_BASELINE_MS = 50.0


def _complexity_verdict(reference_ms: float, learner_ms: float | None) -> str | None:
    if reference_ms < _MIN_BASELINE_MS:
        return None
    if learner_ms is None:
        return None
    ratio = learner_ms / reference_ms
    if ratio <= _OPTIMAL_RATIO:
        return "optimal"
    if ratio <= _ACCEPTABLE_RATIO:
        return "acceptable"
    return "slow"


class EvaluationService:
    """Evaluate pipeline: deterministic hidden-test grading, start to
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
        runtimes = [t for r in results if (t := parse_runtime_ms(r.execution_time_ms)) is not None]
        runtime_ms = sum(runtimes) if runtimes else None
        memories = [r.memory_kb for r in results if r.memory_kb is not None]
        memory_mb = max(memories) / 1024 if memories else None

        metrics = metrics or AttemptMetrics()
        now = datetime.now(timezone.utc)
        submission = Submission(
            id=str(uuid.uuid4()),
            problem_id=problem_id,
            user_id=user_id,
            code_snapshot=code,
            metrics=metrics,
            created_at=now,
        )
        await self._repository.save_submission(submission)

        passed_all = passed == len(version.tests)
        complexity_verdict = None
        if passed_all and version.stress_input and version.stress_runtime_ms:
            complexity_verdict = await self._grade_speed(
                language,
                assemble_program(version.pre_code, code, version.post_code),
                version.stress_input,
                version.stress_runtime_ms,
            )

        if self._mastery_service is not None:
            assistance = metrics.assistance()
            for index, skill_id in enumerate(problem.skill_ids):
                try:
                    # skill_ids[0] is the problem's primary skill; the rest are incidental
                    # and shouldn't move as much on the strength of one problem.
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
            id=str(uuid.uuid4()),
            submission_id=submission.id,
            passed_tests=passed,
            total_tests=len(version.tests),
            runtime_ms=runtime_ms,
            memory_mb=memory_mb,
            complexity_verdict=complexity_verdict,
            created_at=now,
            results=results,
        )
        await self._repository.save_evaluation(evaluation)
        return evaluation

    async def _grade_speed(
        self, language: Language, program: str, stress_input: str, reference_ms: float
    ) -> str | None:
        """One extra sandbox run on the large input the reference was baselined against.
        Any failure here is silent: a missing verdict is fine, a lost grade is not."""
        try:
            request = ExecutionRequest(
                language=language,
                code=program,
                test_cases=[ExecutionTestCase(id="stress", input=stress_input, output_hash="")],
            )
            results = [result async for result in self._executor.execute(request)]
        except Exception:
            logger.warning("Complexity grading failed", exc_info=True)
            return None

        if not results:
            return None
        if results[0].status == ExecutionStatus.TIMEOUT:
            return "slow"
        if results[0].status == ExecutionStatus.ERROR:
            return None
        return _complexity_verdict(reference_ms, parse_runtime_ms(results[0].execution_time_ms))
