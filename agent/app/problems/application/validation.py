import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.execution.domain.executor import CodeExecutor
from app.execution.domain.models import ExecutionRequest, ExecutionStatus
from app.execution.domain.models import TestCase as ExecutionTestCase
from app.llm.domain.provider import LLMProvider
from app.llm.graphs.problem import generate_problem
from app.llm.infrastructure.cache import SqliteLLMCache
from app.problems.domain.models import Problem, ProblemExample, ProblemStatus, ProblemTest, ProblemVersion
from app.problems.domain.repository import ProblemRepository
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.shared.hashing import hash_output
from app.shared.types import Language

_LANGUAGE_EXTENSIONS = {
    Language.PYTHON: "py",
    Language.JAVASCRIPT: "js",
    Language.CPP: "cpp",
    Language.C: "c",
    Language.JAVA: "java",
}


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
            created_at=datetime.now(timezone.utc),
        )
        await self._repository.save(problem)

        if not generated.examples:
            return await self._mark_invalid(problem)

        code_path = self._write_reference_solution(language, generated.reference_solution)
        try:
            request = ExecutionRequest(
                language=language,
                code_path=code_path,
                # output_hash is irrelevant here — we only read back actual_output below,
                # never the PASS/FAIL verdict, since there's nothing trustworthy to compare against yet.
                test_cases=[
                    ExecutionTestCase(id=str(index), input=example.input, output_hash="")
                    for index, example in enumerate(generated.examples)
                ],
            )
            results = [result async for result in self._executor.execute(request)]
        finally:
            Path(code_path).unlink(missing_ok=True)

        broken = len(results) != len(generated.examples) or any(
            r.status in (ExecutionStatus.ERROR, ExecutionStatus.TIMEOUT) for r in results
        )
        if broken:
            return await self._mark_invalid(problem)

        version = ProblemVersion(
            id=str(uuid.uuid4()),
            problem_id=problem.id,
            version=1,
            statement_md=generated.statement_md,
            reference_solution=generated.reference_solution,
            boilerplate=generated.boilerplate,
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

    def _write_reference_solution(self, language: Language, code: str) -> str:
        # Assumes the agent and the Node sandbox share a filesystem (true in dev and in a
        # single-host deploy — the same assumption run.tsx's codePath already makes).
        extension = _LANGUAGE_EXTENSIONS[language]
        fd, path = tempfile.mkstemp(suffix=f".{extension}", prefix="tangerine_ref_")
        with open(fd, "w") as f:
            f.write(code)
        return path
