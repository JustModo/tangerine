from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.curriculum.infrastructure.sqlite_problem_session_repository import (
    SqliteProblemSessionRepository,
)
from app.mastery.infrastructure.sqlite_repository import SqliteUserSkillStateRepository
from app.problems.application.library import compute_stats
from app.problems.infrastructure.sqlite_repository import SqliteProblemRepository
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.revision.application.services import RevisionService
from app.revision.domain.models import RevisionCandidate
from app.users.domain.models import LOCAL_USER_ID, User

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
    return User(id=LOCAL_USER_ID)


@router.get("/{user_id}/progress")
async def get_progress(user_id: str) -> Progress:
    mastery_repository = SqliteUserSkillStateRepository()
    skill_repository = SqliteSkillRepository()
    problem_repository = SqliteProblemRepository()

    states = await mastery_repository.list_for_user(user_id)
    skill_names = await skill_repository.names()
    skills = [
        SkillProgress(
            skill_id=state.skill_id,
            skill_name=skill_names.get(state.skill_id) or state.skill_id,
            mastery_score=state.mastery_score,
            streak=state.streak,
            last_seen_at=state.last_seen_at,
        )
        for state in states
    ]
    skills.sort(key=lambda s: s.mastery_score, reverse=True)

    sessions = await SqliteProblemSessionRepository().list_for_user(user_id)
    stats = compute_stats(sessions, states)

    flagged_sessions = [s for s in sessions if s.flagged]
    flagged_problems = await problem_repository.get_many(
        [s.problem_id for s in flagged_sessions]
    )
    flagged = []
    for session in flagged_sessions:
        problem = flagged_problems.get(session.problem_id)
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
        best_streak=stats.best_streak,
        solved_total=stats.solved_total,
        solved_this_week=stats.solved_this_week,
        revision_queue=await RevisionService(mastery_repository, skill_repository)
        .get_revision_queue(user_id),
        flagged=flagged,
    )
