from datetime import UTC, datetime

from app.mastery.domain.models import UserSkillState
from app.mastery.domain.repository import UserSkillStateRepository

_PASS_DELTA = 0.15
_FAIL_DELTA = -0.1
_MIN_PASS_FRACTION = 0.25
_SECONDARY_FRACTION = 0.4


class MasteryService:
    def __init__(self, repository: UserSkillStateRepository) -> None:
        self._repository = repository

    async def record_result(
        self,
        user_id: str,
        skill_id: str,
        passed: bool,
        assistance: float = 0.0,
        is_primary: bool = True,
    ) -> UserSkillState:
        """Record skill test result and update mastery score and streak."""
        existing = await self._repository.get(user_id, skill_id)
        score = existing.mastery_score if existing else 0.0
        streak = existing.streak if existing else 0

        weight = 1.0 if is_primary else _SECONDARY_FRACTION
        if passed:
            earned = max(1.0 - max(0.0, min(assistance, 1.0)), _MIN_PASS_FRACTION)
            score = min(1.0, score + _PASS_DELTA * earned * weight)
            streak += 1
        else:
            score = max(0.0, score + _FAIL_DELTA * weight)
            streak = 0

        state = UserSkillState(
            user_id=user_id,
            skill_id=skill_id,
            mastery_score=score,
            streak=streak,
            last_seen_at=datetime.now(UTC),
        )
        await self._repository.save(state)
        return state
