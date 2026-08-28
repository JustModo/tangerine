from datetime import UTC, datetime

from app.mastery.domain.repository import UserSkillStateRepository
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.revision.domain.models import RevisionCandidate

_OVERDUE_DAYS = 7.0
# Applied on read rather than by a background job: nothing else needs to run, and a score
# that only moves when someone looks at it is indistinguishable from one that decays
# continuously. Full strength for a fortnight, then down to a floor over ~three months.
_DECAY_GRACE_DAYS = 14.0
_DECAY_PER_DAY = 0.004
_DECAY_FLOOR = 0.3


def decayed_score(mastery_score: float, days_since_seen: float) -> float:
    """A skill practised once in March should not still read as mastered in August."""
    stale_days = max(0.0, days_since_seen - _DECAY_GRACE_DAYS)
    return max(mastery_score * _DECAY_FLOOR, mastery_score - stale_days * _DECAY_PER_DAY)


def suggest_difficulty(mastery_score: float | None, sequence_index: int) -> str:
    """Feeds problem selection with a mastery-aware difficulty instead of pure
    curriculum-position guessing."""
    if mastery_score is not None:
        if mastery_score < 0.3:
            return "easy"
        if mastery_score > 0.7:
            return "hard"
        return "medium"
    if sequence_index == 0:
        return "easy"
    if sequence_index < 3:
        return "medium"
    return "hard"


class RevisionService:
    """Priority = weak_skill + overdue_revision, computed from the
    deterministic mastery/user_skill_state — no LLM call needed for this."""

    def __init__(
        self,
        mastery_repository: UserSkillStateRepository,
        skill_repository: SqliteSkillRepository | None = None,
    ) -> None:
        self._mastery_repository = mastery_repository
        self._skill_repository = skill_repository or SqliteSkillRepository()

    async def get_revision_queue(self, user_id: str) -> list[RevisionCandidate]:
        states = await self._mastery_repository.list_for_user(user_id)
        skill_names = await self._skill_repository.names()
        now = datetime.now(UTC)

        candidates = []
        for state in states:
            days_since_seen = (now - state.last_seen_at).total_seconds() / 86400
            score = decayed_score(state.mastery_score, days_since_seen)
            weak_skill_weight = (1.0 - score) * 2
            overdue_weight = min(days_since_seen / _OVERDUE_DAYS, 1.0)
            priority = weak_skill_weight + overdue_weight

            if score < 0.5:
                reason = "weak_skill"
            elif days_since_seen >= _OVERDUE_DAYS:
                reason = "overdue_revision"
            else:
                reason = "review"

            skill_name = skill_names.get(state.skill_id) or state.skill_id
            candidates.append(
                RevisionCandidate(
                    skill_id=state.skill_id,
                    skill_name=skill_name,
                    reason=reason,
                    priority=priority,
                    mastery_score=score,
                    days_since_seen=days_since_seen,
                )
            )

        candidates.sort(key=lambda c: c.priority, reverse=True)
        return candidates
