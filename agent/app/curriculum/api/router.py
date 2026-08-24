from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.curriculum.application.problem_sessions import ProblemSessionService
from app.curriculum.application.services import CurriculumService
from app.curriculum.domain.models import LessonPlan
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
from app.shared.errors import NotFoundError
from app.shared.progress import stage_stream
from app.shared.sse import sse_stream
from app.shared.types import Language
from app.users.domain.models import LOCAL_USER_ID

router = APIRouter(prefix="/learning-plans", tags=["curriculum"])


def get_service() -> CurriculumService:
    return CurriculumService(
        SqliteLessonPlanRepository(),
        GeminiProvider(),
        llm_cache=SqliteLLMCache(),
        mastery_repository=SqliteUserSkillStateRepository(),
        problem_session_repository=SqliteProblemSessionRepository(),
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
    node_id: str, refresh: bool = False, service: CurriculumService = Depends(get_service)
) -> GeneratedLessonNotes:
    # NotFoundError -> 404 is handled by the app-wide exception handler (app/shared/errors.py)
    return await service.get_node_notes(node_id, refresh=refresh)


@router.get("/{plan_id}")
async def get_plan(
    plan_id: str, service: CurriculumService = Depends(get_service)
) -> LessonPlan:
    plan = await service.get(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Learning plan not found")
    return plan


async def _next_problem_events(
    service: ProblemSessionService, plan_id: str, node_id: str | None
):
    """Streams what preparing this problem is really doing, then the session it produced."""
    try:
        async for event in stage_stream(
            lambda report: service.next_problem(
                plan_id, LOCAL_USER_ID, on_stage=report, node_id=node_id
            ),
            lambda session: {"type": "session", **session.model_dump(mode="json")},
        ):
            yield event
    except NotFoundError as exc:
        # Send error as event frame (200 status already sent).
        yield {"type": "error", "message": str(exc)}


@router.post("/{plan_id}/problems/next")
async def next_problem(
    plan_id: str,
    # Which step was pressed. Omitted means "continue" — the first unfinished one.
    node_id: str | None = None,
    service: ProblemSessionService = Depends(get_problem_session_service),
) -> StreamingResponse:
    stream = sse_stream(
        _next_problem_events(service, plan_id, node_id),
        context=f"next problem plan={plan_id}",
        error_message="Couldn't prepare a problem for this step. Try again in a moment.",
    )
    return StreamingResponse(stream, media_type="text/event-stream")
