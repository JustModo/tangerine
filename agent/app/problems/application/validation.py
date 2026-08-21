import uuid
from datetime import datetime, timezone

from app.execution.domain.executor import CodeExecutor
from app.execution.domain.models import ExecutionRequest, ExecutionStatus
from app.execution.domain.models import TestCase as ExecutionTestCase
from app.llm.domain.provider import LLMProvider
from app.llm.graphs.problem import generate_problem
from app.llm.infrastructure.cache import SqliteLLMCache
from app.problems.domain.models import Problem, ProblemExample, ProblemStatus, ProblemTest, ProblemVersion
from app.problems.domain.repository import ProblemRepository
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.shared.code_assembly import assemble_program
from app.shared.hashing import hash_output
from app.shared.types import Language


class ProblemValidationService:
    """Generates a problem via the problem LangGraph, then proves it out against the real
    sandbox before it can enter the selection pool (plan.md §22-23, §26). Expected test
    outputs always come from actually running the reference solution — never from the
    LLM's claimed example output (plan.md §23)."""

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
        self, skill: str, language: Language, difficulty: str
    ) -> Problem | None:
        generated = await generate_problem(
            self._llm_provider, skill, language.value, difficulty, cache=self._llm_cache
        )

        skill_ids = [
            await self._skill_repository.ensure_skill(name) for name in (generated.skills or [skill])
        ]
        problem = Problem(
            id=str(uuid.uuid4()),
            conceptual_id=str(uuid.uuid4()),
            title=generated.title,
            language=language,
            difficulty=difficulty,
            status=ProblemStatus.VALIDATING,
            skill_ids=skill_ids,
            tags=generated.tags or generated.skills or [skill],
            created_at=datetime.now(timezone.utc),
        )
        await self._repository.save(problem)

        if not generated.examples:
            return await self._mark_invalid(problem)

        reference_program = assemble_program(
            generated.pre_code, generated.reference_user_code, generated.post_code
        )
        request = ExecutionRequest(
            language=language,
            code=reference_program,
            # output_hash is irrelevant here — we only read back actual_output below,
            # never the PASS/FAIL verdict, since there's nothing trustworthy to compare against yet.
            test_cases=[
                ExecutionTestCase(id=str(index), input=example.input, output_hash="")
                for index, example in enumerate(generated.examples)
            ],
        )
        results = [result async for result in self._executor.execute(request)]

        # A reference solution that "succeeds" but prints nothing is just as broken as one
        # that errors — no legitimate DSA answer is an empty string, and an empty-output
        # test silently hashes to hash_output(""), which would let ANY equally-empty
        # submission pass. Catch it here rather than let it reach a real user.
        broken = len(results) != len(generated.examples) or any(
            r.status in (ExecutionStatus.ERROR, ExecutionStatus.TIMEOUT) or not (r.actual_output or "").strip()
            for r in results
        )
        if broken:
            return await self._mark_invalid(problem)

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
                for ex in generated.examples
            ],
            tests=[
                ProblemTest(
                    id=str(uuid.uuid4()),
                    input=example.input,
                    output_hash=hash_output(result.actual_output or ""),
                    is_hidden=True,
                )
                for example, result in zip(generated.examples, results)
            ],
            created_at=datetime.now(timezone.utc),
        )
        await self._repository.save_version(version)

        approved = problem.model_copy(update={"status": ProblemStatus.AVAILABLE})
        await self._repository.save(approved)
        return approved

    async def _mark_invalid(self, problem: Problem) -> None:
        invalid = problem.model_copy(update={"status": ProblemStatus.INVALID})
        await self._repository.save(invalid)
        return None
