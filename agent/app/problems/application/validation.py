import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from app.execution.domain.executor import CodeExecutor
from app.execution.domain.models import ExecutionRequest, ExecutionStatus, parse_runtime_ms
from app.execution.domain.models import TestCase as ExecutionTestCase
from app.llm.domain.provider import LLMProvider
from app.llm.graphs.problem import generate_problem, patch_problem
from app.llm.infrastructure.cache import SqliteLLMCache, cache_key
from app.llm.schemas.problem import GeneratedProblem
from app.problems.application.repair import (
    ValidationFailure,
    apply_patch,
    mismatch_failure,
    no_tests_failure,
    normalise_output,
    runtime_failure,
)
from app.problems.domain.models import (
    Problem,
    ProblemExample,
    ProblemStatus,
    ProblemTest,
    ProblemVersion,
)
from app.problems.domain.repository import ProblemRepository
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.shared.code_assembly import assemble_program
from app.shared.hashing import hash_output
from app.shared.types import Language

logger = logging.getLogger(__name__)

# Most recent titles to tell the generator not to repeat. Enough to keep consecutive
# problems on a skill feeling different, without the list growing forever.
MAX_AVOID_TITLES = 8


def _conceptual_id(title: str) -> str:
    """Identity of the QUESTION rather than of the row. Two generations for one skill
    routinely land on the same classic problem with the same title."""
    return cache_key("conceptual", " ".join(title.lower().split()))


class ProblemValidationService:
    """Generates a problem via the problem LangGraph, then proves it out against the real
    sandbox before it can enter the selection pool. Expected test
    outputs always come from actually running the reference solution — never from the
    LLM's claimed example output."""

    def __init__(
        self,
        repository: ProblemRepository,
        llm_provider: LLMProvider,
        executor: CodeExecutor,
        skill_repository: SqliteSkillRepository | None = None,
        llm_cache: SqliteLLMCache | None = None,
    ) -> None:
        self._repository = repository
        self._llm_provider = llm_provider
        self._executor = executor
        self._skill_repository = skill_repository or SqliteSkillRepository()
        self._llm_cache = llm_cache

    async def generate_and_validate(
        self,
        skill: str,
        language: Language,
        difficulty: str,
        source_problem: str | None = None,
        on_stage: Callable[[str], None] | None = None,
        avoid_titles: list[str] | None = None,
        exclude_problem_ids: list[str] | None = None,
    ) -> Problem | None:
        """Generate, prove it out against the real sandbox, and — when it fails — repair it
        with the failure in hand before falling back to starting over.

        The budget is deliberately the shape of this method rather than a counter: one
        generation, one targeted repair, one fresh generation. A repair is far cheaper than
        a regeneration and fixes the common failures (a signature mismatch, a parse that
        eats the wrong tokens, an example output the reference disagrees with), so it goes
        first; starting over is the escape hatch for when the whole approach is wrong.

        When source_problem is given, the learner pasted that question in and the LLM adapts
        it rather than inventing one. Neither the repair nor the fresh generation may change
        what is being asked — the regeneration re-adapts the SAME source, and the repair is
        barred from touching the statement.

        avoid_titles, when given, is the caller's own do-not-repeat list; a plan passes the
        questions its earlier steps served. Without it, the skill's own titles are used —
        right for the plan-less practice path."""
        stage = on_stage or (lambda _: None)

        if source_problem:
            avoid_titles = []
        elif avoid_titles is None:
            skill_id = await self._skill_repository.ensure_skill(skill)
            avoid_titles = await self._repository.list_titles(skill_id, language)
        # Capped for two reasons: it grows without bound as the bank fills, and it is part of
        # the generation cache key — every extra title is another key nobody else will ever
        # hit. Not repeating a problem is already guaranteed upstream by
        # ProblemSelectionService.find_suitable; this list is only a nudge for variety.
        avoid_titles = avoid_titles[-MAX_AVOID_TITLES:]

        stage("generating")
        generated = await generate_problem(
            self._llm_provider,
            skill,
            language.value,
            difficulty,
            cache=self._llm_cache,
            source_problem=source_problem,
            avoid_titles=avoid_titles,
        )

        # A question the bank already has is served from the bank: already validated, not
        # yet seen by this learner, and no further LLM call.
        duplicate_of = await self._find_duplicate(generated, source_problem, language, exclude_problem_ids)
        if duplicate_of is not None:
            return duplicate_of

        stage("validating")
        problem, failure = await self._validate(
            generated, _conceptual_id(generated.title), skill, language, difficulty
        )
        if problem is not None:
            return problem

        # Repair attempt with failure context (old blind retry didn't have this).
        stage("patching")
        patch = await patch_problem(
            self._llm_provider, generated, failure.kind, failure.detail, language.value
        )
        patched = apply_patch(generated, patch, source_problem)
        if patched is not generated:
            stage("revalidating")
            problem, _ = await self._validate(
                patched, _conceptual_id(patched.title), skill, language, difficulty
            )
            if problem is not None:
                return problem

        # Regenerate without cache (replaying rejected cached answer would loop).
        stage("regenerating")
        generated = await generate_problem(
            self._llm_provider,
            skill,
            language.value,
            difficulty,
            cache=None,
            source_problem=source_problem,
            avoid_titles=avoid_titles + [generated.title],
        )
        duplicate_of = await self._find_duplicate(generated, source_problem, language, exclude_problem_ids)
        if duplicate_of is not None:
            return duplicate_of

        stage("validating")
        problem, _ = await self._validate(
            generated, _conceptual_id(generated.title), skill, language, difficulty
        )
        return problem

    async def _find_duplicate(
        self,
        generated: GeneratedProblem,
        source_problem: str | None,
        language: Language,
        exclude_problem_ids: list[str] | None,
    ) -> Problem | None:
        """The bank's existing take on the question just generated, if it has one. Fuzzy on
        the title rather than an exact hash, which only ever caught identical ones. Never for
        a pasted problem — the learner asked for that exact question."""
        if source_problem:
            return None
        return await self._repository.find_similar(generated.title, language, exclude_problem_ids)

    async def _validate(
        self,
        generated: GeneratedProblem,
        conceptual_id: str,
        skill: str,
        language: Language,
        difficulty: str,
    ) -> tuple[Problem, None] | tuple[None, ValidationFailure]:
        """Returns the approved problem, or None paired with why it was rejected. The
        failure is the input to the repair attempt, so every rejection has to carry one."""
        skill_ids = [
            await self._skill_repository.ensure_skill(name) for name in (generated.skills or [skill])
        ]
        problem = Problem(
            id=str(uuid.uuid4()),
            conceptual_id=conceptual_id,
            title=generated.title,
            language=language,
            difficulty=difficulty,
            status=ProblemStatus.VALIDATING,
            skill_ids=skill_ids,
            tags=generated.tags or generated.skills or [skill],
            created_at=datetime.now(UTC),
        )
        await self._repository.save(problem)

        # Drop empty inputs (causes EOFError on reference solution).
        examples = [ex for ex in generated.examples if ex.input.strip()]
        hidden_tests = [value for value in generated.hidden_tests if value.strip()]
        # Need both examples and hidden tests (without hidden, learner can hardcode answers).
        if not examples or not hidden_tests:
            return await self._mark_invalid(problem, no_tests_failure(examples, hidden_tests))

        reference_program = assemble_program(
            generated.pre_code, generated.reference_user_code, generated.post_code
        )
        graded_inputs = [example.input for example in examples] + hidden_tests
        request = ExecutionRequest(
            language=language,
            code=reference_program,
            # output_hash not used here, only actual_output is read.
            test_cases=[
                ExecutionTestCase(id=str(index), input=value, output_hash="")
                for index, value in enumerate(graded_inputs)
            ],
        )
        results = [result async for result in self._executor.execute(request)]

        # Catch empty outputs (broken reference solution or all-passing submission).
        broken = len(results) != len(graded_inputs) or any(
            r.status in (ExecutionStatus.ERROR, ExecutionStatus.TIMEOUT)
            or not (r.actual_output or "").strip()
            for r in results
        )
        if broken:
            return await self._mark_invalid(problem, runtime_failure(results, len(graded_inputs)))

        # The correctness check: the reference must match the statement's examples.
        if any(
            normalise_output(result.actual_output) != normalise_output(example.output)
            for example, result in zip(examples, results, strict=False)
        ):
            return await self._mark_invalid(problem, mismatch_failure(examples, results))

        stress_input, stress_runtime_ms = await self._measure_stress(
            language, reference_program, generated.stress_test
        )

        version = ProblemVersion(
            id=str(uuid.uuid4()),
            problem_id=problem.id,
            version=1,
            statement_md=generated.statement_md,
            reference_solution=reference_program,
            user_code=generated.user_code,
            pre_code=generated.pre_code,
            post_code=generated.post_code,
            constraints=generated.constraints,
            input_format=generated.input_format,
            output_format=generated.output_format,
            hints=generated.hints,
            examples=[
                ProblemExample(
                    id=str(uuid.uuid4()), input=ex.input, output=ex.output, explanation=ex.explanation
                )
                for ex in examples
            ],
            # Expected outputs from running reference solution, never from LLM.
            tests=[
                ProblemTest(
                    id=str(uuid.uuid4()),
                    input=value,
                    output_hash=hash_output(result.actual_output or ""),
                    is_hidden=True,
                )
                for value, result in zip(graded_inputs, results, strict=True)
            ],
            stress_input=stress_input,
            stress_runtime_ms=stress_runtime_ms,
            created_at=datetime.now(UTC),
        )
        await self._repository.save_version(version)

        approved = problem.model_copy(update={"status": ProblemStatus.AVAILABLE})
        await self._repository.save(approved)
        return approved, None

    async def _measure_stress(
        self, language: Language, reference_program: str, stress_test: str | None
    ) -> tuple[str | None, float | None]:
        """Baseline: how long the reference takes on a large input. A learner's runtime
        means nothing on its own — only against this. A stress input that errors, times out
        or can't be timed is dropped, never fatal: the problem is fine, it just can't be
        graded on speed."""
        if not stress_test or not stress_test.strip():
            return None, None

        request = ExecutionRequest(
            language=language,
            code=reference_program,
            test_cases=[ExecutionTestCase(id="stress", input=stress_test, output_hash="")],
        )
        results = [result async for result in self._executor.execute(request)]
        if not results or results[0].status in (ExecutionStatus.ERROR, ExecutionStatus.TIMEOUT):
            return None, None

        runtime_ms = parse_runtime_ms(results[0].execution_time_ms)
        return (stress_test, runtime_ms) if runtime_ms is not None else (None, None)

    async def _mark_invalid(
        self, problem: Problem, failure: ValidationFailure
    ) -> tuple[None, ValidationFailure]:
        invalid = problem.model_copy(update={"status": ProblemStatus.INVALID})
        await self._repository.save(invalid)
        logger.info("Problem %r rejected (%s): %s", problem.title, failure.kind, failure.detail)
        return None, failure
