
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.curriculum.application.code_helper import CodeHelperService
from app.curriculum.application.problem_sessions import ProblemSessionService
from app.curriculum.domain.problem_chat import ProblemChatMessage
from app.curriculum.domain.problem_session import ProblemSession, ProblemSessionStatus
from app.curriculum.infrastructure.sqlite_problem_session_repository import SqliteProblemSessionRepository
from app.curriculum.infrastructure.sqlite_repository import SqliteLessonPlanRepository
from app.evaluation.application.services import EvaluationService
from app.evaluation.domain.models import AttemptMetrics, Evaluation
from app.evaluation.infrastructure.sqlite_repository import SqliteEvaluationRepository
from app.execution.application.services import ExecutionService
from app.execution.domain.models import ExecutionRequest
from app.execution.domain.models import TestCase as ExecutionTestCase
from app.execution.infrastructure.citron_adapter import CitronAdapter
from app.llm.infrastructure.cache import SqliteLLMCache
from app.llm.infrastructure.gemini.provider import GeminiProvider
from app.mastery.application.services import MasteryService
from app.mastery.infrastructure.sqlite_repository import SqliteUserSkillStateRepository
from app.problems.application.services import ProblemSelectionService
from app.problems.application.validation import ProblemValidationService
from app.problems.infrastructure.sqlite_repository import SqliteProblemRepository
from app.shared.code_assembly import assemble_program
from app.shared.errors import NotFoundError
from app.shared.hashing import hash_output
from app.shared.types import Language
from app.users.domain.models import LOCAL_USER_ID
from app.shared.sse import sse_stream

router = APIRouter(prefix="/problem-sessions", tags=["problem-sessions"])


def _build_validation_service() -> ProblemValidationService:
    return ProblemValidationService(
        SqliteProblemRepository(),
        GeminiProvider(),
        CitronAdapter(),
        llm_cache=SqliteLLMCache(),
    )


def get_service() -> ProblemSessionService:
    return ProblemSessionService(
        SqliteLessonPlanRepository(),
        SqliteProblemSessionRepository(),
        ProblemSelectionService(SqliteProblemRepository()),
        _build_validation_service(),
        mastery_repository=SqliteUserSkillStateRepository(),
    )


class SourceCodeBody(BaseModel):
    source_code: str


class SubmitBody(BaseModel):
    source_code: str
    # What the attempt cost. Only the client knows any of this — the editor clock, the run
    # count and which hints were revealed all live in the browser.
    metrics: AttemptMetrics = AttemptMetrics()


class PracticeBody(BaseModel):
    skill_id: str
    language: Language


class FlagBody(BaseModel):
    flagged: bool


def get_code_helper_service() -> CodeHelperService:
    return CodeHelperService(
        SqliteProblemSessionRepository(), SqliteProblemRepository(), GeminiProvider()
    )


class ChatMessageBody(BaseModel):
    content: str
    source_code: str = ""
    # The client sends its own last-run results: per-test results are never persisted, so
    # the server has no way to reconstruct what the learner is actually looking at.
    last_run: dict | None = None


@router.get("/{session_id}/chat")
async def list_chat(
    session_id: str, service: CodeHelperService = Depends(get_code_helper_service)
) -> list[ProblemChatMessage]:
    return await service.list_messages(session_id)


@router.post("/{session_id}/chat")
async def post_chat(
    session_id: str,
    body: ChatMessageBody,
    service: CodeHelperService = Depends(get_code_helper_service),
) -> StreamingResponse:
    # Checked here, not inside the generator: once StreamingResponse starts, the status
    # line is already 200 and a NotFoundError can only surface as a broken stream.
    if await service.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Problem session not found")

    stream = sse_stream(
        service.send_message(session_id, body.content, body.source_code, body.last_run),
        context=f"code helper problem_session={session_id}",
        error_message="The helper couldn't finish that reply. Try sending it again.",
    )
    return StreamingResponse(stream, media_type="text/event-stream")


@router.post("/practice")
async def start_practice(
    body: PracticeBody, service: ProblemSessionService = Depends(get_service)
) -> ProblemSession:
    """A problem for one skill outside any plan — what the revision queue starts."""
    try:
        return await service.practice_problem(LOCAL_USER_ID, body.skill_id, body.language)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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


@router.patch("/{session_id}/flag")
async def set_flagged(
    session_id: str, body: FlagBody, service: ProblemSessionService = Depends(get_service)
) -> ProblemSession:
    try:
        return await service.set_flagged(session_id, body.flagged)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{session_id}/solution")
async def get_solution(
    session_id: str, service: ProblemSessionService = Depends(get_service)
) -> dict:
    """The reference program, revealed only once the learner has actually solved it.

    This is the exact program the problem was validated with — comparing your own approach
    to a clean one is where a lot of the learning happens. Gated on COMPLETED and nowhere
    else: it is the answer, and every other surface in the app is built to keep it away
    from someone still working."""
    session = await service.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Problem session not found")
    if session.status != ProblemSessionStatus.COMPLETED:
        raise HTTPException(
            status_code=403, detail="Solve this problem first — the solution unlocks once you pass."
        )

    version = await SqliteProblemRepository().get_latest_version(session.problem_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Problem not found")
    return {"reference_solution": version.reference_solution}


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
    "Submit" which grades against hidden tests."""
    session = await service.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Problem session not found")
    await service.save_code(session_id, body.source_code)

    problem_repo = SqliteProblemRepository()
    problem = await problem_repo.get(session.problem_id)
    version = await problem_repo.get_latest_version(session.problem_id)
    if problem is None or version is None:
        raise HTTPException(status_code=404, detail="Problem not found")

    execution_service = ExecutionService(CitronAdapter())
    request = ExecutionRequest(
        language=problem.language,
        code=assemble_program(version.pre_code, body.source_code, version.post_code),
        test_cases=[
            ExecutionTestCase(id=example.id, input=example.input, output_hash=hash_output(example.output))
            for example in version.examples
        ],
    )

    stream = sse_stream(
        execution_service.run(request),
        context=f"run problem_session={session_id}",
        encode=lambda result: f"data: {result.model_dump_json()}\n\n",
        error_message="Couldn't run your code — the sandbox is unreachable.",
    )
    return StreamingResponse(stream, media_type="text/event-stream")


@router.post("/{session_id}/submit")
async def submit(
    session_id: str, body: SubmitBody, service: ProblemSessionService = Depends(get_service)
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
        CitronAdapter(),
        MasteryService(SqliteUserSkillStateRepository()),
    )
    try:
        evaluation = await eval_service.evaluate(
            session.problem_id, LOCAL_USER_ID, problem.language, body.source_code, body.metrics
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    await service.record_submission(session_id, passed=evaluation.passed_tests == evaluation.total_tests)
    return evaluation
