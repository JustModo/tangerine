import uuid
from datetime import datetime, timezone

from app.execution.domain.executor import CodeExecutor
from app.execution.domain.models import ExecutionRequest, ExecutionStatus, parse_runtime_ms
from app.execution.domain.models import TestCase as ExecutionTestCase
from app.llm.domain.provider import LLMProvider
from app.llm.graphs.problem import generate_problem
from app.llm.infrastructure.cache import SqliteLLMCache, cache_key
from app.llm.schemas.problem import GeneratedProblem
from app.problems.domain.models import Problem, ProblemExample, ProblemStatus, ProblemTest, ProblemVersion
from app.problems.domain.repository import ProblemRepository
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.shared.code_assembly import assemble_program
from app.shared.hashing import hash_output
from app.shared.types import Language


# Generation is the expensive step, so this is deliberately small: it covers a bad batch
# or a repeat, not a persistently broken skill.
MAX_ATTEMPTS = 2


def _conceptual_id(title: str) -> str:
    """Identity of the QUESTION rather than of the row. Two generations for one skill
    routinely land on the same classic problem with the same title."""
    return cache_key("conceptual", " ".join(title.lower().split()))


def _normalise_output(value: str | None) -> str:
    """Sandbox stdout vs. a statement's example output: trailing whitespace and line
    endings differ constantly and mean nothing."""
    return "\n".join(line.rstrip() for line in (value or "").strip().splitlines())


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
    ) -> Problem | None:
        """When source_problem is given, the learner pasted that question in and the LLM
        adapts it rather than inventing one — the sandbox validation below is identical
        either way, so a pasted problem still has to actually run before anyone sees it."""
        avoid_titles: list[str] = []
        if not source_problem:
            skill_id = await self._skill_repository.ensure_skill(skill)
            avoid_titles = await self._repository.list_titles(skill_id, language)

        duplicate_of: Problem | None = None
        for attempt in range(MAX_ATTEMPTS):
            generated = await generate_problem(
                self._llm_provider,
                skill,
                language.value,
                difficulty,
                # Only the first attempt may be served from cache: a retry exists precisely
                # because the cached answer was rejected, and replaying it would loop.
                cache=self._llm_cache if attempt == 0 else None,
                source_problem=source_problem,
                avoid_titles=avoid_titles,
            )

            # The generator reached for a problem the bank already has. Retry for a
            # different one rather than storing a near-identical row.
            conceptual_id = _conceptual_id(generated.title)
            if not source_problem:
                existing = await self._repository.find_by_conceptual_id(conceptual_id, language)
                if existing is not None:
                    duplicate_of = duplicate_of or existing
                    avoid_titles = avoid_titles + [generated.title]
                    continue

            problem = await self._validate(generated, conceptual_id, skill, language, difficulty)
            if problem is not None:
                return problem

        # Nothing new survived validation. Serving a problem the learner may have seen
        # before beats failing outright with nothing at all.
        return duplicate_of

    async def _validate(
        self,
        generated: GeneratedProblem,
        conceptual_id: str,
        skill: str,
        language: Language,
        difficulty: str,
    ) -> Problem | None:
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
            created_at=datetime.now(timezone.utc),
        )
        await self._repository.save(problem)

        # An empty stdin is unreadable by every harness the generator writes: `input()`
        # raises EOFError, and Scanner/cin/scanf are no better. The generator is asked for
        # an empty-collection edge case, so it produces one regularly — and the reference
        # then crashes on its own test, failing the whole problem. Dropping the input costs
        # one edge case; keeping it costs the entire problem.
        examples = [ex for ex in generated.examples if ex.input.strip()]
        hidden_tests = [value for value in generated.hidden_tests if value.strip()]
        # No surviving hidden test means every graded input is one the learner can read in
        # the statement, so hardcoding the answers passes. Regenerating costs a call;
        # shipping it costs the meaning of every grade and every mastery score after it.
        if not examples or not hidden_tests:
            return await self._mark_invalid(problem)

        reference_program = assemble_program(
            generated.pre_code, generated.reference_user_code, generated.post_code
        )
        # Grade against the examples AND the extra hidden inputs. Without the extras, every
        # "hidden" test would be an input the learner can already see in the statement, so
        # hardcoding the example answers would pass a submission.
        graded_inputs = [example.input for example in examples] + hidden_tests
        request = ExecutionRequest(
            language=language,
            code=reference_program,
            # output_hash is irrelevant here — we only read back actual_output below,
            # never the PASS/FAIL verdict, since there's nothing trustworthy to compare against yet.
            test_cases=[
                ExecutionTestCase(id=str(index), input=value, output_hash="")
                for index, value in enumerate(graded_inputs)
            ],
        )
        results = [result async for result in self._executor.execute(request)]

        # A reference solution that "succeeds" but prints nothing is just as broken as one
        # that errors — no legitimate DSA answer is an empty string, and an empty-output
        # test silently hashes to hash_output(""), which would let ANY equally-empty
        # submission pass. Catch it here rather than let it reach a real user.
        broken = len(results) != len(graded_inputs) or any(
            r.status in (ExecutionStatus.ERROR, ExecutionStatus.TIMEOUT) or not (r.actual_output or "").strip()
            for r in results
        )
        if broken:
            return await self._mark_invalid(problem)

        # THE correctness check. Everything below trusts the reference solution to DEFINE
        # the right answer, so if it disagrees with the worked examples the statement shows,
        # one of the two is wrong and there is no way to tell which. Shipping it anyway
        # produces a problem where following the statement exactly fails every hidden test,
        # with nothing in the UI able to explain why — the worst failure the app can have.
        for example, result in zip(examples, results):
            if _normalise_output(result.actual_output) != _normalise_output(example.output):
                return await self._mark_invalid(problem)

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
            hints=generated.hints,
            examples=[
                ProblemExample(id=str(uuid.uuid4()), input=ex.input, output=ex.output, explanation=ex.explanation)
                for ex in examples
            ],
            # Expected outputs always come from actually running the reference solution,
            # never from the LLM's claimed output — and only ever as a hash.
            tests=[
                ProblemTest(
                    id=str(uuid.uuid4()),
                    input=value,
                    output_hash=hash_output(result.actual_output or ""),
                    is_hidden=True,
                )
                for value, result in zip(graded_inputs, results)
            ],
            stress_input=stress_input,
            stress_runtime_ms=stress_runtime_ms,
            created_at=datetime.now(timezone.utc),
        )
        await self._repository.save_version(version)

        approved = problem.model_copy(update={"status": ProblemStatus.AVAILABLE})
        await self._repository.save(approved)
        return approved

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

    async def _mark_invalid(self, problem: Problem) -> None:
        invalid = problem.model_copy(update={"status": ProblemStatus.INVALID})
        await self._repository.save(invalid)
        return None
