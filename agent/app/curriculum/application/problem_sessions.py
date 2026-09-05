import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

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

    async def next_problem(
        self,
        plan_id: str,
        user_id: str,
        on_stage: Callable[[str], None] | None = None,
        node_id: str | None = None,
    ) -> ProblemSession:
        """on_stage, when given, reports what this call is actually doing right now
        ("generating", "patching", ...) so the UI can say so honestly instead of guessing
        on a timer. A bank hit reports nothing past "selecting" — it is instant.

        node_id serves THAT step. Without it the first unfinished step wins, which is right
        for a bare "continue" but wrong when the learner pressed play on a specific row —
        they got whatever was earliest instead of what they clicked."""
        if on_stage:
            on_stage("selecting")

        plan = await self._plan_repository.get(plan_id)
        if plan is None:
            raise NotFoundError(f"Lesson plan {plan_id} not found")

        if node_id is not None:
            node = next((n for n in plan.nodes if n.id == node_id), None)
            if node is None:
                raise NotFoundError(f"Step {node_id} is not part of this plan")
            if node.status == LessonNodeStatus.LOCKED:
                raise NotFoundError("That step is still locked — finish the ones before it.")
        else:
            node = next((n for n in plan.nodes if n.status != LessonNodeStatus.DONE), None)
            if node is None:
                raise NotFoundError(f"Lesson plan {plan_id} has no remaining nodes")

        existing = await self._session_repository.get_by_node(node.id)
        if existing is not None:
            return existing

        # A bound step serves that problem directly: no selection, no generation, no
        # sandbox. Checked before every other branch.
        if node.problem_id:
            problem = await self._problem_selection.get(node.problem_id)
            if problem is None:
                raise NotFoundError(
                    "That problem is no longer available — it may have been removed from "
                    "the bank."
                )
            return await self._start_session(plan, node, problem, user_id)

        skill_name = node.skill_name or await self._skill_repository.get_name(node.skill_id) or node.skill_id

        if node.source_problem_md:
            problem = await self._problem_validation.generate_and_validate(
                skill_name,
                plan.language,
                node.difficulty or "medium",
                source_problem=node.source_problem_md,
                on_stage=on_stage,
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
        # Node difficulty overrides mastery estimate; computed before bank lookup.
        difficulty = node.difficulty or suggest_difficulty(mastery_score, node.sequence_index)

        problem = await self._select_or_generate(
            plan, node.skill_id, skill_name, plan.language, difficulty, user_id, on_stage
        )
        if problem is None:
            raise NotFoundError(f"Could not generate a valid problem for skill {skill_name}")

        return await self._start_session(plan, node, problem, user_id)

    async def _select_or_generate(
        self,
        plan,
        skill_id: str,
        skill_name: str,
        language,
        difficulty: str,
        user_id: str,
        on_stage: Callable[[str], None] | None = None,
    ):
        """Bank first, generation on a miss — excluding everything this learner has already
        been served, so practising a skill twice is never the same question twice.

        The do-not-repeat list is scoped to the plan, not the step's skill: a plan's steps
        are all different skills, so a skill-scoped list is empty on every first visit and
        the generator keeps reaching for the same canonical question. Nodes already carry
        the title they served, so this costs no extra lookup."""
        seen_problem_ids = await self._session_repository.list_problem_ids_for_user(user_id)
        criteria = ProblemCriteria(
            skill_id=skill_id,
            language=language,
            difficulty=difficulty,
            exclude_problem_ids=seen_problem_ids,
        )
        problem = await self._problem_selection.find_suitable(criteria)
        if problem is not None:
            return problem
        return await self._problem_validation.generate_and_validate(
            skill_name,
            language,
            difficulty,
            on_stage=on_stage,
            avoid_titles=[node.problem_title for node in plan.nodes if node.problem_title],
            exclude_problem_ids=seen_problem_ids,
        )

    async def start_for_problem(self, user_id: str, problem_id: str) -> ProblemSession:
        """Opens a specific already-generated problem (from the "all problems" list) rather
        than selecting one — resumes an existing session for it if there is one."""
        existing = await self._session_repository.find_for_problem(user_id, problem_id)
        if existing is not None:
            return existing

        now = datetime.now(UTC)
        session = ProblemSession(
            id=str(uuid.uuid4()),
            problem_id=problem_id,
            user_id=user_id,
            status=ProblemSessionStatus.NOT_STARTED,
            created_at=now,
            updated_at=now,
        )
        await self._session_repository.save(session)
        return session

    async def set_flagged_for_problem(
        self, user_id: str, problem_id: str, flagged: bool
    ) -> ProblemSession:
        """Flags/unflags a problem from a list of problems rather than an open session — the
        "all problems" browser has no session yet for one never opened before."""
        session = await self.start_for_problem(user_id, problem_id)
        return await self.set_flagged(session.id, flagged)

    async def set_flagged(self, session_id: str, flagged: bool) -> ProblemSession:
        session = await self._require(session_id)
        updated = session.model_copy(
            update={"flagged": flagged, "updated_at": datetime.now(UTC)}
        )
        await self._session_repository.save(updated)
        return updated

    async def _start_session(self, plan, node, problem, user_id: str) -> ProblemSession:
        now = datetime.now(UTC)

        # A revision plan serves problems the learner already has a session for — flagging
        # one from the browser creates a node-less session. Adopting it keeps the flag and
        # their old code on one row; a second row would split the flag from the progress
        # and list the problem twice on the progress screen.
        existing = await self._session_repository.find_for_problem(user_id, problem.id)
        # Only ever adopt a session belonging to no node — re-pointing one that does would
        # silently steal it from another plan's step.
        # ponytail: when it IS owned, we insert a duplicate and the flag stays on the old
        # row. Make the flag problem-scoped rather than session-scoped if that shows up.
        if existing is not None and existing.lesson_node_id is None:
            # Revising a solved problem means solving it again, so the old answer is
            # cleared. An unfinished attempt keeps its code: that is work in progress.
            already_solved = existing.status == ProblemSessionStatus.COMPLETED
            session = existing.model_copy(
                update={
                    "lesson_node_id": node.id,
                    "lesson_plan_id": plan.id,
                    "source_code": None if already_solved else existing.source_code,
                    # Re-doable: that they solved it before lives in mastery and
                    # evaluations, not here, so nothing is lost by resetting.
                    "status": ProblemSessionStatus.NOT_STARTED,
                    "updated_at": now,
                }
            )
        else:
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
        status = (
            ProblemSessionStatus.IN_PROGRESS
            if session.status == ProblemSessionStatus.NOT_STARTED
            else session.status
        )
        updated = session.model_copy(
            update={
                "source_code": source_code,
                "status": status,
                "updated_at": datetime.now(UTC),
            }
        )
        await self._session_repository.save(updated)
        return updated

    async def record_submission(self, session_id: str, passed: bool) -> ProblemSession:
        session = await self._require(session_id)
        new_status = ProblemSessionStatus.COMPLETED if passed else ProblemSessionStatus.SUBMITTED
        updated = session.model_copy(
            update={"status": new_status, "updated_at": datetime.now(UTC)}
        )
        await self._session_repository.save(updated)

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
