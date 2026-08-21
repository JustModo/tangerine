from fastapi import APIRouter

from app.mastery.application.services import MasteryService
from app.mastery.domain.models import UserSkillState
from app.mastery.infrastructure.sqlite_repository import SqliteUserSkillStateRepository
from app.revision.application.services import RevisionService
from app.revision.domain.models import RevisionCandidate
from app.users.domain.models import User
from app.users.infrastructure.sqlite_repository import SqliteUserRepository

router = APIRouter(prefix="/users", tags=["users"])


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
