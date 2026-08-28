from datetime import UTC, datetime

from app.mastery.domain.models import UserSkillState
from app.mastery.domain.repository import UserSkillStateRepository

_PASS_DELTA = 0.15
_FAIL_DELTA = -0.1
# A pass is never worth nothing, however much help it took — they still shipped a working
# solution, and zeroing it would make the score stop moving for anyone who uses the app as
# intended.
_MIN_PASS_FRACTION = 0.25
# A problem usually touches several skills. Only the first is what it's really about; the
# rest shouldn't reach mastery on the strength of being adjacent to it.
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
        """assistance is 0.0 (solved cold) to 1.0 (hints plus the helper chat). It only
        scales a PASS: a failure after all the help available is still a failure, and
        softening it would let a struggling learner's score drift upward."""
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
