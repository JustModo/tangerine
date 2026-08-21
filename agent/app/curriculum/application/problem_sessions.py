import asyncio
import logging
import uuid
from datetime import datetime, timezone

from app.curriculum.domain.models import LessonNodeStatus
from app.curriculum.domain.problem_session import ProblemSession, ProblemSessionStatus
from app.curriculum.domain.problem_session_repository import ProblemSessionRepository
from app.curriculum.domain.repository import LessonPlanRepository
from app.mastery.domain.repository import UserSkillStateRepository
from app.problems.application.prefetch import PrefetchService
from app.problems.application.services import ProblemSelectionService
from app.problems.application.validation import ProblemValidationService
from app.problems.domain.models import ProblemCriteria
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.revision.application.services import suggest_difficulty
from app.shared.errors import NotFoundError

logger = logging.getLogger(__name__)


class ProblemSessionService:
    """Selects/generates the problem for a lesson node, tracks the user's local source
    file against it, and progresses the curriculum on a passing submission (plan.md §68,
    §6-7's bank-first selection, §29's mastery-aware difficulty)."""

    def __init__(
        self,
        plan_repository: LessonPlanRepository,
        session_repository: ProblemSessionRepository,
        problem_selection: ProblemSelectionService,
        problem_validation: ProblemValidationService,
        skill_repository: SqliteSkillRepository | None = None,
        mastery_repository: UserSkillStateRepository | None = None,
        prefetch_service: PrefetchService | None = None,
    ) -> None:
        self._plan_repository = plan_repository
        self._session_repository = session_repository
        self._problem_selection = problem_selection
        self._problem_validation = problem_validation
        self._skill_repository = skill_repository or SqliteSkillRepository()
        self._mastery_repository = mastery_repository
        self._prefetch_service = prefetch_service

    async def next_problem(self, plan_id: str, user_id: str) -> ProblemSession:
        plan = await self._plan_repository.get(plan_id)
        if plan is None:
            raise NotFoundError(f"Lesson plan {plan_id} not found")

        node = next((n for n in plan.nodes if n.status != LessonNodeStatus.DONE), None)
        if node is None:
            raise NotFoundError(f"Lesson plan {plan_id} has no remaining nodes")

        skill_name = node.skill_name or await self._skill_repository.get_name(node.skill_id) or node.skill_id

        criteria = ProblemCriteria(skill_id=node.skill_id, language=plan.language)
        problem = await self._problem_selection.find_suitable(criteria)
        if problem is None:
            mastery_score = None
            if self._mastery_repository is not None:
                state = await self._mastery_repository.get(user_id, node.skill_id)
                mastery_score = state.mastery_score if state else None
            difficulty = suggest_difficulty(mastery_score, node.sequence_index)
            problem = await self._problem_validation.generate_and_validate(
                skill_name, plan.language, difficulty
            )
        if problem is None:
            raise NotFoundError(f"Could not generate a valid problem for skill {skill_name}")

        now = datetime.now(timezone.utc)
        session = ProblemSession(
            id=str(uuid.uuid4()),
            lesson_node_id=node.id,
            lesson_plan_id=plan.id,
            problem_id=problem.id,
            user_id=user_id,
            status=ProblemSessionStatus.NOT_STARTED,
            created_at=now,
            updated_at=now,
        )
        await self._session_repository.save(session)
        await self._plan_repository.update_node_status(node.id, LessonNodeStatus.IN_PROGRESS)

        if self._prefetch_service is not None:
            next_node = next((n for n in plan.nodes if n.sequence_index == node.sequence_index + 1), None)
            if next_node is not None:
                next_skill_name = (
                    next_node.skill_name
                    or await self._skill_repository.get_name(next_node.skill_id)
                    or next_node.skill_id
                )
                next_difficulty = suggest_difficulty(None, next_node.sequence_index)
                task = asyncio.create_task(
                    self._prefetch_service.prefetch(
                        next_node.skill_id, next_skill_name, plan.language, next_difficulty
                    )
                )
                task.add_done_callback(
                    lambda t: t.exception() and logger.warning("Prefetch task failed", exc_info=t.exception())
                )

        return session

    async def get(self, session_id: str) -> ProblemSession | None:
        return await self._session_repository.get(session_id)

    async def get_for_node(self, lesson_node_id: str) -> ProblemSession | None:
        return await self._session_repository.get_by_node(lesson_node_id)

    async def save_code(self, session_id: str, source_code: str) -> ProblemSession:
        session = await self._require(session_id)
        # Called on every debounced autosave tick as well as on Run/Submit — only ever
        # advance a fresh session into IN_PROGRESS; never regress a SUBMITTED/COMPLETED
        # session back on a later autosave (unlike the old one-time file-pick flow, this
        # fires repeatedly for the lifetime of the page).
        status = (
            ProblemSessionStatus.IN_PROGRESS
            if session.status == ProblemSessionStatus.NOT_STARTED
            else session.status
        )
        updated = session.model_copy(
            update={
                "source_code": source_code,
                "status": status,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        await self._session_repository.save(updated)
        return updated

    async def record_submission(self, session_id: str, passed: bool) -> ProblemSession:
        session = await self._require(session_id)
        new_status = ProblemSessionStatus.COMPLETED if passed else ProblemSessionStatus.SUBMITTED
        updated = session.model_copy(
            update={"status": new_status, "updated_at": datetime.now(timezone.utc)}
        )
        await self._session_repository.save(updated)

        if passed:
            node = await self._plan_repository.get_node(session.lesson_node_id)
            if node is not None:
                await self._plan_repository.update_node_status(node.id, LessonNodeStatus.DONE)
                await self._plan_repository.unlock_next_node(node.lesson_plan_id, node.sequence_index)
        return updated

    async def _require(self, session_id: str) -> ProblemSession:
        session = await self._session_repository.get(session_id)
        if session is None:
            raise NotFoundError(f"Problem session {session_id} not found")
        return session
