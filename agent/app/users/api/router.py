from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from app.curriculum.domain.problem_session import ProblemSessionStatus
from app.curriculum.infrastructure.sqlite_problem_session_repository import (
    SqliteProblemSessionRepository,
)
from app.mastery.application.services import MasteryService
from app.mastery.domain.models import UserSkillState
from app.mastery.infrastructure.sqlite_repository import SqliteUserSkillStateRepository
from app.problems.infrastructure.sqlite_repository import SqliteProblemRepository
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.revision.application.services import RevisionService
from app.revision.domain.models import RevisionCandidate
from app.users.domain.models import User
from app.users.infrastructure.sqlite_repository import SqliteUserRepository

router = APIRouter(prefix="/users", tags=["users"])


class SkillProgress(BaseModel):
    skill_id: str
    skill_name: str
    mastery_score: float
    streak: int
    last_seen_at: datetime


class SolvedProblem(BaseModel):
    problem_session_id: str
    problem_id: str
    title: str
    difficulty: str
    flagged: bool
    updated_at: datetime


class Progress(BaseModel):
    """Everything the progress screen needs, in one round trip. Assembled from tables that
    until now were written and never read."""

    skills: list[SkillProgress]
    best_streak: int
    solved_total: int
    solved_this_week: int
    revision_queue: list[RevisionCandidate]
    flagged: list[SolvedProblem]


@router.get("/me")
async def get_current_user() -> User:
    return await SqliteUserRepository().ensure_default_user()


@router.get("/{user_id}/mastery")
async def get_mastery(user_id: str) -> list[UserSkillState]:
    service = MasteryService(SqliteUserSkillStateRepository())
    return await service.list_for_user(user_id)


@router.get("/{user_id}/revision-queue")
async def get_revision_queue(user_id: str) -> list[RevisionCandidate]:
    service = RevisionService(SqliteUserSkillStateRepository())
    return await service.get_revision_queue(user_id)


@router.get("/{user_id}/progress")
async def get_progress(user_id: str) -> Progress:
    mastery_repository = SqliteUserSkillStateRepository()
    skill_repository = SqliteSkillRepository()
    problem_repository = SqliteProblemRepository()

    states = await mastery_repository.list_for_user(user_id)
    skills = [
        SkillProgress(
            skill_id=state.skill_id,
            skill_name=await skill_repository.get_name(state.skill_id) or state.skill_id,
            mastery_score=state.mastery_score,
            streak=state.streak,
            last_seen_at=state.last_seen_at,
        )
        for state in states
    ]
    skills.sort(key=lambda s: s.mastery_score, reverse=True)

    sessions = await SqliteProblemSessionRepository().list_for_user(user_id)
    completed = [s for s in sessions if s.status == ProblemSessionStatus.COMPLETED]
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    flagged = []
    for session in sessions:
        if not session.flagged:
            continue
        problem = await problem_repository.get(session.problem_id)
        if problem is None:
            continue
        flagged.append(
            SolvedProblem(
                problem_session_id=session.id,
                problem_id=problem.id,
                title=problem.title,
                difficulty=problem.difficulty,
                flagged=True,
                updated_at=session.updated_at,
            )
        )

    return Progress(
        skills=skills,
        best_streak=max((state.streak for state in states), default=0),
        solved_total=len(completed),
        solved_this_week=sum(1 for s in completed if s.updated_at >= week_ago),
        revision_queue=await RevisionService(mastery_repository, skill_repository)
        .get_revision_queue(user_id),
        flagged=flagged,
    )
