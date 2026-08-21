from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.execution.infrastructure.composite_executor import CompositeExecutor
from app.llm.infrastructure.cache import SqliteLLMCache
from app.llm.infrastructure.gemini.provider import GeminiProvider
from app.problems.application.services import ProblemSelectionService
from app.problems.application.validation import ProblemValidationService
from app.problems.domain.models import Problem, ProblemCriteria, ProblemExample
from app.problems.infrastructure.sqlite_repository import SqliteProblemRepository
from app.shared.types import Language

router = APIRouter(prefix="/problems", tags=["problems"])


def get_service() -> ProblemSelectionService:
    return ProblemSelectionService(SqliteProblemRepository())


def get_validation_service() -> ProblemValidationService:
    return ProblemValidationService(
        SqliteProblemRepository(),
        GeminiProvider(),
        CompositeExecutor(),
        llm_cache=SqliteLLMCache(),
    )


class GenerateProblemBody(BaseModel):
    skill: str
    language: Language
    difficulty: str


@router.post("/generate")
async def generate_problem_endpoint(
    body: GenerateProblemBody,
    service: ProblemValidationService = Depends(get_validation_service),
) -> Problem:
    problem = await service.generate_and_validate(body.skill, body.language, body.difficulty)
    if problem is None:
        raise HTTPException(status_code=422, detail="Generated problem failed sandbox validation")
    return problem


class ProblemDetail(BaseModel):
    id: str
    title: str
    language: Language
    difficulty: str
    statement_md: str
    boilerplate: str
    constraints: str | None
    hints: list[str]
    tags: list[str]
    examples: list[ProblemExample]


@router.get("/{problem_id}")
async def get_problem(
    problem_id: str, service: ProblemSelectionService = Depends(get_service)
) -> ProblemDetail:
    problem = await service.get(problem_id)
    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found")
    version = await SqliteProblemRepository().get_latest_version(problem_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Problem has no content yet")
    return ProblemDetail(
        id=problem.id,
        title=problem.title,
        language=problem.language,
        difficulty=problem.difficulty,
        statement_md=version.statement_md,
        boilerplate=version.boilerplate,
        constraints=version.constraints,
        hints=version.hints,
        tags=problem.tags,
        examples=version.examples,
    )


@router.get("")
async def search_problems(
    skill_id: str | None = Query(default=None),
    language: Language | None = Query(default=None),
    difficulty: str | None = Query(default=None),
    service: ProblemSelectionService = Depends(get_service),
) -> Problem | None:
    criteria = ProblemCriteria(skill_id=skill_id, language=language, difficulty=difficulty)
    return await service.find_suitable(criteria)
