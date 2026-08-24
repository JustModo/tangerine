from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.curriculum.infrastructure.sqlite_problem_session_repository import (
    SqliteProblemSessionRepository,
)
from app.problems.application.services import ProblemSelectionService
from app.problems.domain.models import Problem, ProblemExample
from app.problems.infrastructure.sqlite_repository import SqliteProblemRepository
from app.shared.types import Language
from app.users.domain.models import LOCAL_USER_ID

router = APIRouter(prefix="/problems", tags=["problems"])


def get_service() -> ProblemSelectionService:
    return ProblemSelectionService(SqliteProblemRepository())


class ProblemSummary(BaseModel):
    id: str
    title: str
    language: Language
    difficulty: str
    tags: list[str]
    created_at: str
    flagged: bool = False


class ProblemsPage(BaseModel):
    items: list[ProblemSummary]
    total: int
    page: int
    page_size: int


# Registered ahead of GET /{problem_id} below — otherwise "all" would be swallowed as a
# problem_id and this route would never be reached.
@router.get("/all")
async def list_all_problems(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None),
    language: Language | None = Query(default=None),
) -> ProblemsPage:
    items, total = await SqliteProblemRepository().list_all(
        page, page_size, q, language.value if language else None
    )
    sessions = await SqliteProblemSessionRepository().list_for_user(LOCAL_USER_ID)
    flagged_problem_ids = {s.problem_id for s in sessions if s.flagged}
    return ProblemsPage(
        items=[
            ProblemSummary(
                id=p.id, title=p.title, language=p.language, difficulty=p.difficulty,
                tags=p.tags, created_at=str(p.created_at), flagged=p.id in flagged_problem_ids,
            )
            for p in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


class ProblemDetail(BaseModel):
    id: str
    title: str
    language: Language
    difficulty: str
    statement_md: str
    user_code: str
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
        user_code=version.user_code,
        constraints=version.constraints,
        hints=version.hints,
        tags=problem.tags,
        examples=version.examples,
    )
