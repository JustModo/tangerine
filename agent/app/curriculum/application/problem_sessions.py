import logging
import uuid
from datetime import datetime, timezone

from app.curriculum.domain.models import LessonNodeStatus
from app.curriculum.domain.problem_session import ProblemSession, ProblemSessionStatus
from app.curriculum.domain.problem_session_repository import ProblemSessionRepository
from app.curriculum.domain.repository import LessonPlanRepository
from app.mastery.domain.repository import UserSkillStateRepository
from app.problems.application.services import ProblemSelectionService
from app.problems.application.validation import ProblemValidationService
from app.problems.domain.models import ProblemCriteria
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.revision.application.services import suggest_difficulty
from app.shared.errors import NotFoundError

logger = logging.getLogger(__name__)



class ProblemSessionService:
    """Selects/generates the problem for a lesson node, tracks the user's local source
    file against it, and progresses the curriculum on a passing submission.

    Generation happens when the learner presses Start on a node, and only then: nothing is
    produced ahead of time for a step they may never reach."""

    def __init__(
        self,
        plan_repository: LessonPlanRepository,
        session_repository: ProblemSessionRepository,
        problem_selection: ProblemSelectionService,
        problem_validation: ProblemValidationService,
        skill_repository: SqliteSkillRepository | None = None,
        mastery_repository: UserSkillStateRepository | None = None,
    ) -> None:
        self._plan_repository = plan_repository
        self._session_repository = session_repository
        self._problem_selection = problem_selection
        self._problem_validation = problem_validation
        self._skill_repository = skill_repository or SqliteSkillRepository()
        self._mastery_repository = mastery_repository

    async def next_problem(self, plan_id: str, user_id: str) -> ProblemSession:
        plan = await self._plan_repository.get(plan_id)
        if plan is None:
            raise NotFoundError(f"Lesson plan {plan_id} not found")

        node = next((n for n in plan.nodes if n.status != LessonNodeStatus.DONE), None)
        if node is None:
            raise NotFoundError(f"Lesson plan {plan_id} has no remaining nodes")

        existing = await self._session_repository.get_by_node(node.id)
        if existing is not None:
            return existing

        skill_name = node.skill_name or await self._skill_repository.get_name(node.skill_id) or node.skill_id

        # A node carrying a pasted problem must serve THAT question — never a bank hit for
        # a merely similar skill — so selection is skipped entirely for it.
        if node.source_problem_md:
            problem = await self._problem_validation.generate_and_validate(
                skill_name,
                plan.language,
                node.difficulty or "medium",
                source_problem=node.source_problem_md,
            )
            if problem is None:
                raise NotFoundError(
                    "Could not prepare the problem you pasted — it may be missing examples "
                    "or an input format that can be run automatically."
                )
            return await self._start_session(plan, node, problem, user_id)

        mastery_score = None
        if self._mastery_repository is not None:
            state = await self._mastery_repository.get(user_id, node.skill_id)
            mastery_score = state.mastery_score if state else None
        # An explicit per-node difficulty (set by the curriculum, or by the user asking the
        # chat to make a step harder/easier) wins over the mastery/position guess. Computed
        # BEFORE the bank lookup, not just for generation — a lookup that ignores it will
        # happily hand back an easy problem for a step the learner asked to be hard.
        difficulty = node.difficulty or suggest_difficulty(mastery_score, node.sequence_index)

        problem = await self._select_or_generate(
            node.skill_id, skill_name, plan.language, difficulty, user_id
        )
        if problem is None:
            raise NotFoundError(f"Could not generate a valid problem for skill {skill_name}")

        return await self._start_session(plan, node, problem, user_id)

    async def _select_or_generate(
        self, skill_id: str, skill_name: str, language, difficulty: str, user_id: str
    ):
        """Bank first, generation on a miss — excluding everything this learner has already
        been served, so practising a skill twice is never the same question twice."""
        criteria = ProblemCriteria(
            skill_id=skill_id,
            language=language,
            difficulty=difficulty,
            exclude_problem_ids=await self._session_repository.list_problem_ids_for_user(user_id),
        )
        problem = await self._problem_selection.find_suitable(criteria)
        if problem is not None:
            return problem
        return await self._problem_validation.generate_and_validate(
            skill_name, language, difficulty
        )

    async def practice_problem(self, user_id: str, skill_id: str, language) -> ProblemSession:
        """A problem for one skill, outside any plan — what the revision queue's Practice
        button starts. Difficulty follows current mastery rather than a curriculum
        position, since there is no position."""
        skill_name = await self._skill_repository.get_name(skill_id) or skill_id

        mastery_score = None
        if self._mastery_repository is not None:
            state = await self._mastery_repository.get(user_id, skill_id)
            mastery_score = state.mastery_score if state else None

        problem = await self._select_or_generate(
            skill_id, skill_name, language, suggest_difficulty(mastery_score, 0), user_id
        )
        if problem is None:
            raise NotFoundError(f"Could not generate a valid problem for skill {skill_name}")

        now = datetime.now(timezone.utc)
        session = ProblemSession(
            id=str(uuid.uuid4()),
            problem_id=problem.id,
            user_id=user_id,
            status=ProblemSessionStatus.NOT_STARTED,
            created_at=now,
            updated_at=now,
        )
        await self._session_repository.save(session)
        return session

    async def set_flagged(self, session_id: str, flagged: bool) -> ProblemSession:
        session = await self._require(session_id)
        updated = session.model_copy(
            update={"flagged": flagged, "updated_at": datetime.now(timezone.utc)}
        )
        await self._session_repository.save(updated)
        return updated

    async def list_for_user(self, user_id: str) -> list[ProblemSession]:
        return await self._session_repository.list_for_user(user_id)

    async def _start_session(self, plan, node, problem, user_id: str) -> ProblemSession:
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

        # A practice session has no node to advance — it exists precisely to be outside
        # the plan.
        if passed and session.lesson_node_id is not None:
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
