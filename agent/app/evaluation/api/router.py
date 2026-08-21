from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.evaluation.application.services import EvaluationService
from app.evaluation.domain.models import Evaluation
from app.evaluation.infrastructure.sqlite_repository import SqliteEvaluationRepository
from app.execution.infrastructure.composite_executor import CompositeExecutor
from app.llm.infrastructure.gemini.provider import GeminiProvider
from app.mastery.application.services import MasteryService
from app.mastery.infrastructure.sqlite_repository import SqliteUserSkillStateRepository
from app.problems.infrastructure.sqlite_repository import SqliteProblemRepository
from app.shared.types import Language
from app.users.domain.models import LOCAL_USER_ID

router = APIRouter(prefix="/evaluations", tags=["evaluation"])


def get_service() -> EvaluationService:
    return EvaluationService(
        SqliteEvaluationRepository(),
        SqliteProblemRepository(),
        CompositeExecutor(),
        GeminiProvider(),
        MasteryService(SqliteUserSkillStateRepository()),
    )


class EvaluateBody(BaseModel):
    problem_id: str
    language: Language
    code: str


@router.post("")
async def evaluate(
    body: EvaluateBody, service: EvaluationService = Depends(get_service)
) -> Evaluation:
    return await service.evaluate(body.problem_id, LOCAL_USER_ID, body.language, body.code)


class SampleFailure(BaseModel):
    input: str
    actual_output: str | None = None
    error: str | None = None


class CoachBody(BaseModel):
    title: str
    passed: int
    total: int
    sample_failures: list[SampleFailure] = []


class CoachResponse(BaseModel):
    feedback: str | None


@router.post("/coach")
async def coach(
    body: CoachBody, service: EvaluationService = Depends(get_service)
) -> CoachResponse:
    feedback = await service.generate_feedback(
        body.title, body.passed, body.total, [f.model_dump() for f in body.sample_failures]
    )
    return CoachResponse(feedback=feedback)
