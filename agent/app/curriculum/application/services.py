import uuid
from datetime import UTC, datetime
from functools import partial

from app.curriculum.application.lesson_verification import verify_lesson_code
from app.curriculum.domain.models import LessonNode, LessonNodeStatus, LessonPlan
from app.curriculum.domain.problem_session import ProblemSessionStatus
from app.curriculum.domain.problem_session_repository import ProblemSessionRepository
from app.curriculum.domain.repository import LessonPlanRepository
from app.execution.domain.executor import CodeExecutor
from app.llm.domain.provider import LLMProvider
from app.llm.graphs.curriculum import generate_curriculum
from app.llm.graphs.lesson_notes import generate_lesson_notes
from app.llm.graphs.plan_edit import revise_curriculum
from app.llm.infrastructure.cache import SqliteLLMCache
from app.llm.schemas.lesson_notes import GeneratedLessonNotes
from app.mastery.domain.repository import UserSkillStateRepository
from app.problems.domain.models import ProblemStatus
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.shared.errors import ConflictError, NotFoundError
from app.shared.types import Language

_DIFFICULTY_BY_RATING = {1: "easy", 2: "easy", 3: "medium", 4: "hard", 5: "hard"}


def _difficulty_label(rating: int) -> str:
    return _DIFFICULTY_BY_RATING.get(rating, "medium")


KNOWN_SKILL_THRESHOLD = 0.8


class CurriculumService:
    """Lesson plan creation, node management, and lesson notes generation."""

    def __init__(
        self,
        repository: LessonPlanRepository,
        llm_provider: LLMProvider,
        skill_repository: SqliteSkillRepository | None = None,
        llm_cache: SqliteLLMCache | None = None,
        mastery_repository: UserSkillStateRepository | None = None,
        problem_session_repository: ProblemSessionRepository | None = None,
        problem_repository=None,
        executor: CodeExecutor | None = None,
    ) -> None:
        self._repository = repository
        self._llm_provider = llm_provider
        self._skill_repository = skill_repository or SqliteSkillRepository()
        self._llm_cache = llm_cache
        self._mastery_repository = mastery_repository
        self._problem_session_repository = problem_session_repository
        self._problem_repository = problem_repository
        self._executor = executor

    async def create_draft(
        self,
        session_id: str,
        topic: str,
        language: Language,
        level: str,
        step_count: int | None = None,
        target_problem: str | None = None,
        user_id: str | None = None,
    ) -> LessonPlan:
        """Create a new lesson plan with generated sequence of lesson nodes."""
        known_skills = await self._known_skills(user_id)
        plan = LessonPlan(
            id=str(uuid.uuid4()),
            session_id=session_id,
            topic=topic,
            language=language,
            level=level,
            version=1,
            created_at=datetime.now(UTC),
        )
        await self._repository.save(plan)

        prerequisite_count = step_count - 1 if step_count is not None and target_problem else step_count
        generated_nodes = []
        if prerequisite_count is None or prerequisite_count > 0:
            generated = await generate_curriculum(
                self._llm_provider,
                topic,
                language.value,
                level,
                cache=self._llm_cache,
                step_count=prerequisite_count,
                target_problem=target_problem,
                known_skills=sorted(known_skills),
            )
            generated_nodes = generated.nodes

        nodes = []
        seen_skill_ids: set[str] = set()
        for generated_node in generated_nodes:
            skill_id = await self._skill_repository.ensure_skill(generated_node.skill)
            if skill_id in seen_skill_ids:
                continue
            seen_skill_ids.add(skill_id)
            already_known = generated_node.skill.strip().lower() in known_skills
            nodes.append(
                LessonNode(
                    id=str(uuid.uuid4()),
                    lesson_plan_id=plan.id,
                    skill_id=skill_id,
                    sequence_index=0,
                    status=LessonNodeStatus.DONE if already_known else LessonNodeStatus.LOCKED,
                    difficulty=_difficulty_label(generated_node.difficulty),
                    created_at=datetime.now(UTC),
                )
            )

        if target_problem:
            nodes.append(
                LessonNode(
                    id=str(uuid.uuid4()),
                    lesson_plan_id=plan.id,
                    skill_id=await self._skill_repository.ensure_skill(topic),
                    sequence_index=len(nodes),
                    status=LessonNodeStatus.LOCKED,
                    difficulty="hard",
                    source_problem_md=target_problem,
                    created_at=datetime.now(UTC),
                )
            )

        if nodes:
            await self._repository.save_nodes(self._ensure_startable(nodes))

        return await self._reloaded(plan.id, plan)

    async def create_practice_plan(
        self, session_id: str, problem_ids: list[str], topic: str = "Revision"
    ) -> LessonPlan:
        """Create a plan bound directly to existing problem IDs."""
        if self._problem_repository is None:
            raise NotFoundError("Practice plans are not available without a problem bank.")

        problems = [
            problem
            for problem_id in problem_ids
            if (problem := await self._problem_repository.get(problem_id)) is not None
        ]
        if not problems:
            raise NotFoundError("None of those problems are in the bank any more.")

        plan = LessonPlan(
            id=str(uuid.uuid4()),
            session_id=session_id,
            topic=topic,
            language=problems[0].language,
            level="revision",
            version=1,
            created_at=datetime.now(UTC),
        )
        await self._repository.save(plan)

        now = datetime.now(UTC)
        nodes = [
            LessonNode(
                id=str(uuid.uuid4()),
                lesson_plan_id=plan.id,
                skill_id=problem.skill_ids[0]
                if problem.skill_ids
                else await self._skill_repository.ensure_skill(topic),
                sequence_index=index,
                status=LessonNodeStatus.LOCKED,
                difficulty=problem.difficulty,
                problem_id=problem.id,
                created_at=now,
            )
            for index, problem in enumerate(problems)
        ]
        await self._repository.save_nodes(self._ensure_startable(nodes))

        return await self._reloaded(plan.id, plan)

    async def _known_skills(self, user_id: str | None) -> set[str]:
        """Fetch normalised names of skills mastered by user above threshold."""
        if user_id is None or self._mastery_repository is None:
            return set()
        known = set()
        for state in await self._mastery_repository.list_for_user(user_id):
            if state.mastery_score < KNOWN_SKILL_THRESHOLD:
                continue
            name = await self._skill_repository.get_name(state.skill_id)
            if name:
                known.add(name.strip().lower())
        return known

    async def get(self, plan_id: str) -> LessonPlan | None:
        return await self._repository.get(plan_id)

    async def set_plan_language(self, plan_id: str, language: Language) -> LessonPlan:
        """Update the plan's programming language and invalidate unsubmitted problem sessions."""
        plan = await self._require_plan(plan_id)
        if language == plan.language:
            return plan
        updated = plan.model_copy(update={"language": language, "version": plan.version + 1})
        await self._repository.save(updated)
        await self._invalidate_unsubmitted(node.id for node in plan.nodes)
        return await self._repository.get(plan_id) or updated

    async def _invalidate_unsubmitted(self, lesson_node_ids) -> None:
        """Delete unsubmitted problem sessions for the given lesson nodes."""
        if self._problem_session_repository is None:
            return
        for lesson_node_id in lesson_node_ids:
            await self._problem_session_repository.delete_unsubmitted_for_node(lesson_node_id)

    async def _session_problem(self, node_id: str):
        """Fetch problem session and bound problem for a lesson node."""
        if self._problem_session_repository is None or self._problem_repository is None:
            return None, None
        session = await self._problem_session_repository.get_by_node(node_id)
        if session is None:
            return None, None
        return (
            session,
            await self._problem_repository.get(session.problem_id),
        )

    async def step_problem(self, plan_id: str, step: str):
        """Fetch lesson node and problem for a specific step."""
        plan = await self._require_plan(plan_id)
        node = self._resolve_step(plan, step)
        _, problem = await self._session_problem(node.id)
        return node, problem

    async def regenerate_step_problem(self, plan_id: str, step: str) -> LessonPlan:
        """Invalidate the problem on a step to trigger regeneration on next open."""
        plan = await self._require_plan(plan_id)
        target = self._resolve_step(plan, step)
        if target.problem_id:
            raise ConflictError(
                f"step {target.sequence_index + 1} is pinned to one specific problem they "
                "asked for, so there is nothing to regenerate"
            )

        session, problem = await self._session_problem(target.id)
        if session is None:
            raise ConflictError(
                f"step {target.sequence_index + 1} has no question yet — it generates a "
                "fresh one the first time they open it"
            )
        if session.status not in (
            ProblemSessionStatus.NOT_STARTED,
            ProblemSessionStatus.IN_PROGRESS,
        ):
            raise ConflictError(
                f"step {target.sequence_index + 1} has already been submitted for grading, "
                "and discarding graded work would lose their attempt"
            )

        if problem is not None and self._problem_repository is not None:
            await self._problem_repository.save(
                problem.model_copy(update={"status": ProblemStatus.INVALID})
            )
        await self._invalidate_unsubmitted([target.id])
        return await self._reloaded(plan_id, plan)

    def _resolve_step(self, plan: LessonPlan, step: str) -> LessonNode:
        """Resolve a step identifier (1-indexed sequence number or skill name) to a LessonNode."""
        stripped = step.strip()
        if stripped.isdigit():
            index = int(stripped) - 1
            if 0 <= index < len(plan.nodes):
                return plan.nodes[index]
        normalized = stripped.lower()
        for node in plan.nodes:
            if (node.skill_name or "").strip().lower() == normalized:
                return node
        raise NotFoundError(f"No step matching '{step}' in this plan")

    @staticmethod
    def _ensure_startable(nodes: list[LessonNode]) -> list[LessonNode]:
        """Ensure sequential reindexing and unlock the first unfinished lesson node."""
        ordered = [node.model_copy(update={"sequence_index": index}) for index, node in enumerate(nodes)]
        first = next(
            (i for i, node in enumerate(ordered) if node.status != LessonNodeStatus.DONE), None
        )
        if first is not None and ordered[first].status == LessonNodeStatus.LOCKED:
            ordered[first] = ordered[first].model_copy(
                update={"status": LessonNodeStatus.AVAILABLE}
            )
        return ordered

    async def _reloaded(self, plan_id: str, fallback: LessonPlan) -> LessonPlan:
        return await self._repository.get(plan_id) or fallback

    async def _require_plan(self, plan_id: str) -> LessonPlan:
        plan = await self._repository.get(plan_id)
        if plan is None:
            raise NotFoundError(f"Lesson plan {plan_id} not found")
        return plan

    async def set_step_difficulty(self, plan_id: str, step: str, difficulty: str) -> LessonPlan:
        """Update the difficulty of a specific step and invalidate unsubmitted sessions."""
        plan = await self._require_plan(plan_id)
        target = self._resolve_step(plan, step)
        if difficulty == target.difficulty:
            return plan
        nodes = [
            node.model_copy(update={"difficulty": difficulty}) if node.id == target.id else node
            for node in plan.nodes
        ]
        await self._repository.replace_nodes(plan.id, nodes)
        await self._invalidate_unsubmitted([target.id])
        return await self._reloaded(plan_id, plan)

    async def add_step(
        self, plan_id: str, skill: str, difficulty: str | None = None, position: int | None = None
    ) -> LessonPlan:
        """Add a new step to the lesson plan at the specified position."""
        plan = await self._require_plan(plan_id)
        skill_id = await self._skill_repository.ensure_skill(skill)
        if any(node.skill_id == skill_id for node in plan.nodes):
            raise ConflictError(f"'{skill}' is already a step on this plan.")

        new_node = LessonNode(
            id=str(uuid.uuid4()),
            lesson_plan_id=plan.id,
            skill_id=skill_id,
            sequence_index=0,
            status=LessonNodeStatus.LOCKED,
            difficulty=difficulty or "medium",
            created_at=datetime.now(UTC),
        )
        nodes = list(plan.nodes)
        insert_at = len(nodes) if position is None else max(0, min(position - 1, len(nodes)))
        nodes.insert(insert_at, new_node)
        await self._repository.replace_nodes(plan.id, self._ensure_startable(nodes))
        return await self._reloaded(plan_id, plan)

    async def add_problem_step(self, plan_id: str, problem_id: str) -> LessonPlan:
        """Append an existing problem to the lesson plan as a new step."""
        if self._problem_repository is None:
            raise NotFoundError("Adding an existing problem needs a problem bank.")
        plan = await self._require_plan(plan_id)
        problem = await self._problem_repository.get(problem_id)
        if problem is None:
            raise NotFoundError("That problem is no longer in the bank.")
        if any(node.problem_id == problem_id for node in plan.nodes):
            raise ConflictError(f"'{problem.title}' is already a step on this plan.")

        new_node = LessonNode(
            id=str(uuid.uuid4()),
            lesson_plan_id=plan.id,
            skill_id=(
                problem.skill_ids[0]
                if problem.skill_ids
                else await self._skill_repository.ensure_skill(problem.title)
            ),
            sequence_index=0,
            status=LessonNodeStatus.AVAILABLE,
            difficulty=problem.difficulty,
            problem_id=problem.id,
            created_at=datetime.now(UTC),
        )
        await self._repository.replace_nodes(plan.id, self._ensure_startable([*plan.nodes, new_node]))
        return await self._reloaded(plan_id, plan)

    async def remove_step(self, plan_id: str, step: str) -> LessonPlan:
        """Remove a step from the lesson plan."""
        plan = await self._require_plan(plan_id)
        target = self._resolve_step(plan, step)
        if target.status == LessonNodeStatus.DONE:
            raise NotFoundError("Can't remove a completed step")
        nodes = [node for node in plan.nodes if node.id != target.id]
        await self._repository.replace_nodes(plan.id, self._ensure_startable(nodes))
        return await self._reloaded(plan_id, plan)

    async def reorder_step(self, plan_id: str, step: str, to_position: int) -> LessonPlan:
        """Move a step to a new position in the plan."""
        plan = await self._require_plan(plan_id)
        target = self._resolve_step(plan, step)
        nodes = [node for node in plan.nodes if node.id != target.id]
        insert_at = max(0, min(to_position - 1, len(nodes)))
        nodes.insert(insert_at, target)
        await self._repository.replace_nodes(plan.id, self._ensure_startable(nodes))
        return await self._reloaded(plan_id, plan)

    async def edit_plan(self, plan_id: str, instruction: str) -> LessonPlan:
        """Apply free-text curriculum revision to the plan while preserving completed progress."""
        plan = await self._require_plan(plan_id)

        current_steps = "\n".join(
            f"{node.sequence_index + 1}. {node.skill_name or node.skill_id} "
            f"(difficulty: {node.difficulty or 'unset'}, status: {node.status.value})"
            for node in plan.nodes
        )
        revised = await revise_curriculum(
            self._llm_provider,
            plan.topic,
            plan.language.value,
            plan.level,
            current_steps,
            instruction,
        )

        existing_by_skill: dict[str, list[LessonNode]] = {}
        for node in plan.nodes:
            existing_by_skill.setdefault((node.skill_name or "").strip().lower(), []).append(node)

        nodes: list[LessonNode] = []
        matched_ids: set[str] = set()
        redifficultied_ids: set[str] = set()
        seen_skills: set[str] = set()
        for step in revised.steps:
            skill_key = step.skill.strip().lower()
            if skill_key in seen_skills:
                continue
            seen_skills.add(skill_key)
            candidates = existing_by_skill.get(skill_key, [])
            match = next((c for c in candidates if c.id not in matched_ids), None)
            difficulty = step.difficulty
            if match is not None:
                matched_ids.add(match.id)
                if difficulty != match.difficulty:
                    redifficultied_ids.add(match.id)
                nodes.append(match.model_copy(update={"difficulty": difficulty}))
            else:
                nodes.append(
                    LessonNode(
                        id=str(uuid.uuid4()),
                        lesson_plan_id=plan.id,
                        skill_id=await self._skill_repository.ensure_skill(step.skill),
                        sequence_index=0,
                        status=LessonNodeStatus.LOCKED,
                        difficulty=difficulty,
                        created_at=datetime.now(UTC),
                    )
                )

        rescued = sorted(
            (n for n in plan.nodes if n.status == LessonNodeStatus.DONE and n.id not in matched_ids),
            key=lambda n: n.sequence_index,
        )
        nodes = rescued + nodes

        await self._repository.replace_nodes(plan.id, self._ensure_startable(nodes))
        await self._invalidate_unsubmitted(redifficultied_ids)
        return await self._reloaded(plan_id, plan)

    async def get_node_notes(self, node_id: str, refresh: bool = False) -> GeneratedLessonNotes:
        """Generate or retrieve cached lesson notes for a node."""
        node = await self._repository.get_node(node_id)
        if node is None:
            raise NotFoundError(f"Lesson node {node_id} not found")
        if node.status == LessonNodeStatus.LOCKED:
            raise NotFoundError(f"Lesson notes for node {node_id} are not available until it is unlocked")

        plan = await self._repository.get(node.lesson_plan_id)
        if plan is None:
            raise NotFoundError(f"Lesson plan {node.lesson_plan_id} not found")

        _, problem = await self._session_problem(node_id)

        return await generate_lesson_notes(
            self._llm_provider,
            node.skill_name or node.skill_id,
            plan.language.value,
            plan.level,
            cache=self._llm_cache,
            refresh=refresh,
            problem_id=problem.id if problem else None,
            problem_title=problem.title if problem else None,
            tags=problem.tags if problem else None,
            statement_md=problem.statement_md if problem else None,
            reference_solution=problem.reference_solution if problem else None,
            verifier=partial(verify_lesson_code, self._executor) if self._executor else None,
        )

    async def list_for_session(self, session_id: str) -> list[LessonPlan]:
        return await self._repository.list_for_session(session_id)
