import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from app.execution.domain.executor import CodeExecutor
from app.execution.domain.models import ExecutionRequest, ExecutionStatus
from app.execution.domain.models import TestCase as ExecutionTestCase
from app.llm.domain.provider import LLMProvider
from app.llm.graphs.problem import generate_problem, patch_problem
from app.llm.schemas.problem import GeneratedProblem
from app.problems.application.repair import (
    ValidationFailure,
    apply_patch,
    execution_failure,
    mismatch_failure,
    no_tests_failure,
)
from app.problems.domain.models import (
    Problem,
    ProblemExample,
    ProblemStatus,
    ProblemTest,
)
from app.problems.domain.repository import ProblemRepository
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.shared.code_assembly import assemble_program
from app.shared.fuzzy import match_score
from app.shared.hashing import comparable_output, hash_output
from app.shared.types import Language

logger = logging.getLogger(__name__)

# Most recent titles to avoid repeating
MAX_AVOID_TITLES = 8

# How close two titles in the SAME plan may be before the second is a repeat. Deliberately
# high: the same underlying task dressed in a genuinely different situation is wanted, and
# only a near-restatement of a step the learner already has counts as a duplicate.
REPEAT_TITLE_THRESHOLD = 0.75


def _repeats_a_plan_title(title: str, plan_titles: list[str]) -> bool:
    return any(
        max(match_score(title, other), match_score(other, title)) >= REPEAT_TITLE_THRESHOLD
        for other in plan_titles
    )


class ProblemValidationService:
    """Generates and validates coding problems against the execution sandbox."""

    def __init__(
        self,
        repository: ProblemRepository,
        llm_provider: LLMProvider,
        executor: CodeExecutor,
        skill_repository: SqliteSkillRepository | None = None,
    ) -> None:
        self._repository = repository
        self._llm_provider = llm_provider
        self._executor = executor
        self._skill_repository = skill_repository or SqliteSkillRepository()

    async def generate_and_validate(
        self,
        skill: str,
        language: Language,
        difficulty: str,
        source_problem: str | None = None,
        on_stage: Callable[[str], None] | None = None,
        avoid_titles: list[str] | None = None,
        areas: tuple[str, str] | None = None,
        twist: str | None = None,
    ) -> Problem | None:
        """Generate problem candidate, validate against sandbox, and attempt repair if rejected."""
        stage = on_stage or (lambda _: None)
        plan_titles = [] if source_problem else list(avoid_titles or [])

        if source_problem:
            avoid_titles = []
        elif avoid_titles is None:
            skill_id = await self._skill_repository.ensure_skill(skill)
            avoid_titles = await self._repository.list_titles(skill_id, language)
        avoid_titles = avoid_titles[-MAX_AVOID_TITLES:]

        generated = None
        for attempt in range(2):
            stage("generating" if attempt == 0 else "regenerating")
            generated = await generate_problem(
                self._llm_provider,
                skill,
                language.value,
                difficulty,
                source_problem=source_problem,
                avoid_titles=avoid_titles if attempt == 0 else avoid_titles + [generated.title],
                on_stage=stage,
                areas=areas,
                twist=twist,
            )

            if attempt == 0 and _repeats_a_plan_title(generated.title, plan_titles):
                logger.info(
                    "Problem %r repeats a step already in this plan, regenerating",
                    generated.title,
                )
                continue

            problem = await self._validate_or_repair(
                generated, skill, language, difficulty, source_problem, stage
            )
            if problem is not None:
                return problem
        return None

    async def _validate_or_repair(
        self,
        generated: GeneratedProblem,
        skill: str,
        language: Language,
        difficulty: str,
        source_problem: str | None,
        stage: Callable[[str], None],
    ) -> Problem | None:
        """Validate generated problem and attempt patch repair on failure."""
        stage("validating")
        result = await self._validate(generated, skill, language, difficulty)
        if isinstance(result, Problem):
            return result

        stage("patching")
        patch = await patch_problem(
            self._llm_provider, generated, result.kind, result.detail, language.value
        )
        patched = apply_patch(generated, patch, source_problem)
        if patched is generated:
            return None

        stage("revalidating")
        repaired = await self._validate(patched, skill, language, difficulty)
        return repaired if isinstance(repaired, Problem) else None

    async def _validate(
        self,
        generated: GeneratedProblem,
        skill: str,
        language: Language,
        difficulty: str,
    ) -> Problem | ValidationFailure:
        """Validate generated problem test cases and execution outputs against reference solution."""
        skill_ids: list[str] = []
        for name in [skill, *generated.skills]:
            skill_id = await self._skill_repository.ensure_skill(name)
            if skill_id not in skill_ids:
                skill_ids.append(skill_id)
        problem = Problem(
            id=str(uuid.uuid4()),
            title=generated.title,
            language=language,
            difficulty=difficulty,
            status=ProblemStatus.VALIDATING,
            skill_ids=skill_ids,
            tags=generated.tags or generated.skills or [skill],
            created_at=datetime.now(UTC),
        )
        await self._repository.save(problem)

        examples = [ex for ex in generated.examples if ex.input.strip()]
        hidden_tests = [value for value in generated.hidden_tests if value.strip()]
        if not examples or not hidden_tests:
            return await self._mark_invalid(problem, no_tests_failure(examples, hidden_tests))

        reference_program = assemble_program(
            generated.pre_code, generated.reference_user_code, generated.post_code
        )
        graded_inputs = [example.input for example in examples] + hidden_tests
        request = ExecutionRequest(
            language=language,
            code=reference_program,
            test_cases=[
                ExecutionTestCase(id=str(index), input=value, output_hash="")
                for index, value in enumerate(graded_inputs)
            ],
        )
        results = [result async for result in self._executor.execute(request)]

        crashed = any(r.status in (ExecutionStatus.ERROR, ExecutionStatus.TIMEOUT) for r in results)
        all_empty = all(not (r.actual_output or "").strip() for r in results)
        if len(results) != len(graded_inputs) or crashed or all_empty:
            return await self._mark_invalid(
                problem, execution_failure(results, len(graded_inputs), all_empty=all_empty)
            )

        if any(
            comparable_output(result.actual_output) != comparable_output(example.output)
            for example, result in zip(examples, results, strict=False)
        ):
            return await self._mark_invalid(problem, mismatch_failure(examples, results))

        examples_list = [
            ProblemExample(
                id=str(uuid.uuid4()), input=ex.input, output=ex.output, explanation=ex.explanation
            )
            for ex in examples
        ]
        tests_list = [
            ProblemTest(
                id=str(uuid.uuid4()),
                input=value,
                output_hash=hash_output(result.actual_output or ""),
            )
            for value, result in zip(graded_inputs, results, strict=True)
        ]

        approved = problem.model_copy(
            update={
                "status": ProblemStatus.AVAILABLE,
                "statement_md": generated.statement_md,
                "reference_solution": reference_program,
                "user_code": generated.user_code,
                "pre_code": generated.pre_code,
                "post_code": generated.post_code,
                "constraints": generated.constraints,
                "input_format": generated.input_format,
                "output_format": generated.output_format,
                "hints": generated.hints,
                "examples": examples_list,
                "tests": tests_list,
            }
        )
        await self._repository.save(approved)
        return approved

    async def _mark_invalid(
        self, problem: Problem, failure: ValidationFailure
    ) -> ValidationFailure:
        invalid = problem.model_copy(update={"status": ProblemStatus.INVALID})
        await self._repository.save(invalid)
        logger.info("Problem %r rejected (%s): %s", problem.title, failure.kind, failure.detail)
        return failure
