from datetime import datetime, timezone

from app.mastery.domain.models import UserSkillState
from app.mastery.domain.repository import UserSkillStateRepository

# Simple deterministic scoring (plan.md §28: "start with a simple deterministic scoring
# algorithm... don't build an elaborate AI mastery system initially").
_PASS_DELTA = 0.15
_FAIL_DELTA = -0.1


class MasteryService:
    def __init__(self, repository: UserSkillStateRepository) -> None:
        self._repository = repository

    async def record_result(self, user_id: str, skill_id: str, passed: bool) -> UserSkillState:
        existing = await self._repository.get(user_id, skill_id)
        score = existing.mastery_score if existing else 0.0
        streak = existing.streak if existing else 0

        if passed:
            score = min(1.0, score + _PASS_DELTA)
            streak += 1
        else:
            score = max(0.0, score + _FAIL_DELTA)
            streak = 0

        state = UserSkillState(
            user_id=user_id,
            skill_id=skill_id,
            mastery_score=score,
            streak=streak,
            last_seen_at=datetime.now(timezone.utc),
        )
        await self._repository.save(state)
        return state

    async def list_for_user(self, user_id: str) -> list[UserSkillState]:
        return await self._repository.list_for_user(user_id)
