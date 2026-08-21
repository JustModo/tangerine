from typing import Protocol

from app.mastery.domain.models import UserSkillState


class UserSkillStateRepository(Protocol):
    async def get(self, user_id: str, skill_id: str) -> UserSkillState | None: ...

    async def save(self, state: UserSkillState) -> None: ...

    async def list_for_user(self, user_id: str) -> list[UserSkillState]: ...
