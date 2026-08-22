from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.curriculum.application.problem_sessions import ProblemSessionService
from app.curriculum.application.services import CurriculumService
from app.curriculum.domain.models import LessonPlan
from app.curriculum.domain.problem_session import ProblemSession
from app.curriculum.infrastructure.sqlite_problem_session_repository import SqliteProblemSessionRepository
from app.curriculum.infrastructure.sqlite_repository import SqliteLessonPlanRepository
from app.execution.infrastructure.citron_adapter import CitronAdapter
from app.llm.infrastructure.cache import SqliteLLMCache
from app.llm.infrastructure.gemini.provider import GeminiProvider
from app.llm.schemas.lesson_notes import GeneratedLessonNotes
from app.mastery.infrastructure.sqlite_repository import SqliteUserSkillStateRepository
from app.problems.application.services import ProblemSelectionService
from app.problems.application.validation import ProblemValidationService
from app.problems.infrastructure.sqlite_repository import SqliteProblemRepository
from app.shared.types import Language
from app.users.domain.models import LOCAL_USER_ID

router = APIRouter(prefix="/learning-plans", tags=["curriculum"])


def get_service() -> CurriculumService:
    return CurriculumService(
        SqliteLessonPlanRepository(),
        GeminiProvider(),
        llm_cache=SqliteLLMCache(),
        mastery_repository=SqliteUserSkillStateRepository(),
    )


def _build_validation_service() -> ProblemValidationService:
    return ProblemValidationService(
        SqliteProblemRepository(),
        GeminiProvider(),
        CitronAdapter(),
        llm_cache=SqliteLLMCache(),
    )


def get_problem_session_service() -> ProblemSessionService:
    return ProblemSessionService(
        SqliteLessonPlanRepository(),
        SqliteProblemSessionRepository(),
        ProblemSelectionService(SqliteProblemRepository()),
        _build_validation_service(),
        mastery_repository=SqliteUserSkillStateRepository(),
    )


class CreatePlanBody(BaseModel):
    session_id: str
    topic: str
    language: Language
    level: str


@router.post("")
async def create_plan(
    body: CreatePlanBody, service: CurriculumService = Depends(get_service)
) -> LessonPlan:
    return await service.create_draft(
        body.session_id, body.topic, body.language, body.level, user_id=LOCAL_USER_ID
    )


@router.get("")
async def list_plans(
    session_id: str, service: CurriculumService = Depends(get_service)
) -> list[LessonPlan]:
    return await service.list_for_session(session_id)


@router.get("/nodes/{node_id}/notes")
async def get_node_notes(
    node_id: str, service: CurriculumService = Depends(get_service)
) -> GeneratedLessonNotes:
    # NotFoundError -> 404 is handled by the app-wide exception handler (app/shared/errors.py)
    return await service.get_node_notes(node_id)


@router.get("/{plan_id}")
async def get_plan(
    plan_id: str, service: CurriculumService = Depends(get_service)
) -> LessonPlan:
    plan = await service.get(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Learning plan not found")
    return plan


@router.post("/{plan_id}/problems/next")
async def next_problem(
    plan_id: str, service: ProblemSessionService = Depends(get_problem_session_service)
) -> ProblemSession:
    return await service.next_problem(plan_id, LOCAL_USER_ID)
