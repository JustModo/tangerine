from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.curriculum.application.problem_sessions import ProblemSessionService
from app.curriculum.domain.problem_session import ProblemSession
from app.curriculum.infrastructure.sqlite_problem_session_repository import SqliteProblemSessionRepository
from app.curriculum.infrastructure.sqlite_repository import SqliteLessonPlanRepository
from app.evaluation.application.services import EvaluationService
from app.evaluation.domain.models import Evaluation
from app.evaluation.infrastructure.sqlite_repository import SqliteEvaluationRepository
from app.execution.application.services import ExecutionService
from app.execution.domain.models import ExecutionRequest
from app.execution.domain.models import TestCase as ExecutionTestCase
from app.execution.infrastructure.composite_executor import CompositeExecutor
from app.llm.infrastructure.cache import SqliteLLMCache
from app.llm.infrastructure.gemini.provider import GeminiProvider
from app.mastery.application.services import MasteryService
from app.mastery.infrastructure.sqlite_repository import SqliteUserSkillStateRepository
from app.problems.application.prefetch import PrefetchService
from app.problems.application.services import ProblemSelectionService
from app.problems.application.validation import ProblemValidationService
from app.problems.infrastructure.sqlite_repository import SqliteProblemRepository
from app.shared.errors import NotFoundError
from app.shared.hashing import hash_output
from app.users.domain.models import LOCAL_USER_ID

router = APIRouter(prefix="/problem-sessions", tags=["problem-sessions"])


def _build_validation_service() -> ProblemValidationService:
    return ProblemValidationService(
        SqliteProblemRepository(),
        GeminiProvider(),
        CompositeExecutor(),
        llm_cache=SqliteLLMCache(),
    )


def get_service() -> ProblemSessionService:
    return ProblemSessionService(
        SqliteLessonPlanRepository(),
        SqliteProblemSessionRepository(),
        ProblemSelectionService(SqliteProblemRepository()),
        _build_validation_service(),
        mastery_repository=SqliteUserSkillStateRepository(),
        prefetch_service=PrefetchService(
            ProblemSelectionService(SqliteProblemRepository()), _build_validation_service()
        ),
    )


class SourceCodeBody(BaseModel):
    source_code: str


@router.get("/by-node/{lesson_node_id}")
async def get_session_for_node(
    lesson_node_id: str, service: ProblemSessionService = Depends(get_service)
) -> ProblemSession:
    """Lets a learner revisit a completed lesson node's problem — the node's most recent
    session, even after it's been marked DONE, rather than only ever creating new ones."""
    session = await service.get_for_node(lesson_node_id)
    if session is None:
        raise HTTPException(status_code=404, detail="No problem session for this lesson node")
    return session


@router.get("/{session_id}")
async def get_session(
    session_id: str, service: ProblemSessionService = Depends(get_service)
) -> ProblemSession:
    session = await service.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Problem session not found")
    return session


@router.patch("/{session_id}/code")
async def save_code(
    session_id: str, body: SourceCodeBody, service: ProblemSessionService = Depends(get_service)
) -> ProblemSession:
    return await service.save_code(session_id, body.source_code)


@router.post("/{session_id}/run")
async def run(
    session_id: str, body: SourceCodeBody, service: ProblemSessionService = Depends(get_service)
) -> StreamingResponse:
    """Runs the problem's visible examples (not graded) — the "Run" action, distinct from
    "Submit" which grades against hidden tests (plan.md §12, §16)."""
    session = await service.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Problem session not found")
    await service.save_code(session_id, body.source_code)

    problem_repo = SqliteProblemRepository()
    problem = await problem_repo.get(session.problem_id)
    version = await problem_repo.get_latest_version(session.problem_id)
    if problem is None or version is None:
        raise HTTPException(status_code=404, detail="Problem not found")

    execution_service = ExecutionService(CompositeExecutor())
    request = ExecutionRequest(
        language=problem.language,
        code=body.source_code,
        test_cases=[
            ExecutionTestCase(id=example.id, input=example.input, output_hash=hash_output(example.output))
            for example in version.examples
        ],
    )

    async def event_stream():
        async for result in execution_service.run(request):
            yield f"data: {result.model_dump_json()}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/{session_id}/submit")
async def submit(
    session_id: str, body: SourceCodeBody, service: ProblemSessionService = Depends(get_service)
) -> Evaluation:
    session = await service.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Problem session not found")
    await service.save_code(session_id, body.source_code)

    problem_repo = SqliteProblemRepository()
    problem = await problem_repo.get(session.problem_id)
    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found")

    eval_service = EvaluationService(
        SqliteEvaluationRepository(),
        problem_repo,
        CompositeExecutor(),
        GeminiProvider(),
        MasteryService(SqliteUserSkillStateRepository()),
    )
    try:
        evaluation = await eval_service.evaluate(
            session.problem_id, LOCAL_USER_ID, problem.language, body.source_code
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    await service.record_submission(session_id, passed=evaluation.passed_tests == evaluation.total_tests)
    return evaluation
