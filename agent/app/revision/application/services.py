from datetime import datetime, timezone

from app.mastery.domain.repository import UserSkillStateRepository
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.revision.domain.models import RevisionCandidate

_OVERDUE_DAYS = 7.0


def suggest_difficulty(mastery_score: float | None, sequence_index: int) -> str:
    """Feeds problem selection with a mastery-aware difficulty instead of pure curriculum-position guessing."""
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
        now = datetime.now(timezone.utc)

        candidates = []
        for state in states:
            days_since_seen = (now - state.last_seen_at).total_seconds() / 86400
            weak_skill_weight = (1.0 - state.mastery_score) * 2
            overdue_weight = min(days_since_seen / _OVERDUE_DAYS, 1.0)
            priority = weak_skill_weight + overdue_weight

            if state.mastery_score < 0.5:
                reason = "weak_skill"
            elif days_since_seen >= _OVERDUE_DAYS:
                reason = "overdue_revision"
            else:
                reason = "review"

            skill_name = await self._skill_repository.get_name(state.skill_id) or state.skill_id
            candidates.append(
                RevisionCandidate(
                    skill_id=state.skill_id, skill_name=skill_name, reason=reason, priority=priority
                )
            )

        candidates.sort(key=lambda c: c.priority, reverse=True)
        return candidates
