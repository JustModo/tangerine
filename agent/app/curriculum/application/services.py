import uuid
from datetime import datetime, timezone

from app.curriculum.domain.models import LessonNode, LessonNodeStatus, LessonPlan
from app.curriculum.domain.problem_session_repository import ProblemSessionRepository
from app.curriculum.domain.repository import LessonPlanRepository
from app.llm.domain.provider import LLMProvider
from app.llm.graphs.curriculum import generate_curriculum
from app.llm.graphs.lesson_notes import generate_lesson_notes
from app.llm.graphs.plan_edit import revise_curriculum
from app.llm.infrastructure.cache import SqliteLLMCache
from app.llm.schemas.lesson_notes import GeneratedLessonNotes
from app.mastery.domain.repository import UserSkillStateRepository
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.shared.errors import ConflictError, NotFoundError
from app.shared.types import Language


# The curriculum LLM rates each step 1-5; problem selection speaks easy/medium/hard.
_DIFFICULTY_BY_RATING = {1: "easy", 2: "easy", 3: "medium", 4: "hard", 5: "hard"}


def _difficulty_label(rating: int) -> str:
    return _DIFFICULTY_BY_RATING.get(rating, "medium")


# Above this the learner has repeatedly solved problems on the skill unaided, so the plan
# marks it DONE rather than making them repeat it.
KNOWN_SKILL_THRESHOLD = 0.8


class CurriculumService:
    """Lesson plan creation and per-node lesson notes. A plan's nodes are populated
    immediately via the curriculum LangGraph and are usable right
    away — there's no accept step, and the most recently created plan is the active one."""

    def __init__(
        self,
        repository: LessonPlanRepository,
        llm_provider: LLMProvider,
        skill_repository: SqliteSkillRepository | None = None,
        llm_cache: SqliteLLMCache | None = None,
        mastery_repository: UserSkillStateRepository | None = None,
        problem_session_repository: ProblemSessionRepository | None = None,
        problem_repository=None,
    ) -> None:
        self._repository = repository
        self._llm_provider = llm_provider
        self._skill_repository = skill_repository or SqliteSkillRepository()
        self._llm_cache = llm_cache
        self._mastery_repository = mastery_repository
        self._problem_session_repository = problem_session_repository
        self._problem_repository = problem_repository

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
        """step_count honours an explicit "just 2 lessons" request; target_problem is a
        question the learner pasted in, in which case the generated steps are prerequisites
        and one extra final step is appended that serves that exact problem.

        user_id lets the plan account for what this learner already knows — steps on skills
        they have demonstrably mastered start DONE instead of blocking the ones they came
        for."""
        known_skills = await self._known_skills(user_id)
        plan = LessonPlan(
            id=str(uuid.uuid4()),
            session_id=session_id,
            topic=topic,
            language=language,
            level=level,
            version=1,
            created_at=datetime.now(timezone.utc),
        )
        await self._repository.save(plan)

        # A pasted problem occupies the final step, so the LLM only has to produce the
        # prerequisites — one fewer than the learner asked for in total. "Just this one
        # problem" therefore means zero prerequisites, and we skip curriculum generation
        # altogether rather than padding the plan with a step they explicitly didn't want.
        prerequisite_count = (
            step_count - 1 if step_count is not None and target_problem else step_count
        )
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

        # The prompt asks for distinct skills; this enforces it. sequence_index stays 0 —
        # _ensure_startable reindexes below, so a skipped node leaves no gap.
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
                    created_at=datetime.now(timezone.utc),
                )
            )

        if target_problem:
            # The course ends on the learner's own question. Carrying the statement on the
            # node means it's adapted lazily, when they actually reach it.
            nodes.append(
                LessonNode(
                    id=str(uuid.uuid4()),
                    lesson_plan_id=plan.id,
                    skill_id=await self._skill_repository.ensure_skill(topic),
                    sequence_index=len(nodes),
                    status=LessonNodeStatus.LOCKED,
                    difficulty="hard",
                    source_problem_md=target_problem,
                    created_at=datetime.now(timezone.utc),
                )
            )

        if nodes:
            await self._repository.save_nodes(self._ensure_startable(nodes))

        return await self._repository.get(plan.id) or plan

    async def create_practice_plan(
        self, session_id: str, problem_ids: list[str], topic: str = "Revision"
    ) -> LessonPlan:
        """A plan whose steps ARE these exact problems — for revising work already done.

        No LLM call anywhere: the steps are given, and each node's skill, difficulty and
        language come off the problem itself. That is also why every step is instant to
        open — next_problem's problem_id branch skips selection and generation entirely."""
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
            # The problems already exist in one language; a plan-level override would be a
            # lie, since none of them will be regenerated.
            language=problems[0].language,
            level="revision",
            version=1,
            created_at=datetime.now(timezone.utc),
        )
        await self._repository.save(plan)

        now = datetime.now(timezone.utc)
        nodes = [
            LessonNode(
                id=str(uuid.uuid4()),
                lesson_plan_id=plan.id,
                # Straight off the problem — ensure_skill takes a NAME and would create a
                # junk row, and the problem already carries resolved ids.
                skill_id=problem.skill_ids[0] if problem.skill_ids else await self._skill_repository.ensure_skill(topic),
                sequence_index=index,
                status=LessonNodeStatus.LOCKED,
                difficulty=problem.difficulty,
                problem_id=problem.id,
                created_at=now,
            )
            for index, problem in enumerate(problems)
        ]
        await self._repository.save_nodes(self._ensure_startable(nodes))

        return await self._repository.get(plan.id) or plan

    async def _known_skills(self, user_id: str | None) -> set[str]:
        """Normalised names of skills this learner has already demonstrated. Compared by
        name because that is all the curriculum generator emits — it never sees skill ids."""
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
        """Switches what language the plan's remaining problems generate in — a pure
        language swap, not a step revision, so unlike edit_plan this touches no step, no
        LLM call, and no node reconciliation. Every node's NOT_STARTED/IN_PROGRESS problem
        session is discarded (see _invalidate_unsubmitted) so it regenerates fresh in the
        new language next time it's opened — a SUBMITTED or COMPLETED session is real,
        graded work and is left exactly as it is."""
        plan = await self._require_plan(plan_id)
        if language == plan.language:
            return plan
        updated = plan.model_copy(update={"language": language, "version": plan.version + 1})
        await self._repository.save(updated)
        await self._invalidate_unsubmitted(node.id for node in plan.nodes)
        return await self._repository.get(plan_id) or updated

    async def _invalidate_unsubmitted(self, lesson_node_ids) -> None:
        """Discards a node's problem session unless it's been submitted for grading — the
        shared hook behind "what a node's problem should be just changed": a language swap
        (every node) or an edited step's difficulty (that one node). Without this,
        next_problem's get_by_node short-circuit keeps resurfacing the stale problem, even
        for an in-progress attempt that no longer fits."""
        if self._problem_session_repository is None:
            return
        for lesson_node_id in lesson_node_ids:
            await self._problem_session_repository.delete_unsubmitted_for_node(lesson_node_id)

    def _resolve_step(self, plan: LessonPlan, step: str) -> LessonNode:
        """A step named either by its 1-indexed position (as shown in the plan UI) or its
        skill name — whichever the user actually said. Shared by every operation that
        targets one existing step, so "which step did they mean" is resolved exactly the
        same way everywhere."""
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
        """Reindexes sequentially and unlocks the first unfinished step — every structural
        change (add/remove/reorder a step, or an LLM-driven rework) must leave the plan in a
        state the learner can actually continue from, never all-locked."""
        ordered = [node.model_copy(update={"sequence_index": index}) for index, node in enumerate(nodes)]
        for index, node in enumerate(ordered):
            if node.status != LessonNodeStatus.DONE:
                if node.status == LessonNodeStatus.LOCKED:
                    ordered[index] = node.model_copy(update={"status": LessonNodeStatus.AVAILABLE})
                break
        return ordered

    async def _require_plan(self, plan_id: str) -> LessonPlan:
        plan = await self._repository.get(plan_id)
        if plan is None:
            raise NotFoundError(f"Lesson plan {plan_id} not found")
        return plan

    async def set_step_difficulty(self, plan_id: str, step: str, difficulty: str) -> LessonPlan:
        """Changes one step's difficulty in place — no LLM call, no other step touched.
        Invalidates only that step's not-yet-submitted problem session (see
        _invalidate_unsubmitted) so it regenerates at the new difficulty."""
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
        return await self._repository.get(plan_id) or plan

    async def add_step(
        self, plan_id: str, skill: str, difficulty: str | None = None, position: int | None = None
    ) -> LessonPlan:
        """Inserts a brand new step — no existing step's row, session, or progress is
        touched, so nothing needs invalidating."""
        plan = await self._require_plan(plan_id)
        skill_id = await self._skill_repository.ensure_skill(skill)
        # Same guard add_problem_step has.
        if any(node.skill_id == skill_id for node in plan.nodes):
            raise ConflictError(f"'{skill}' is already a step on this plan.")

        new_node = LessonNode(
            id=str(uuid.uuid4()),
            lesson_plan_id=plan.id,
            skill_id=skill_id,
            sequence_index=0,  # reindexed below
            status=LessonNodeStatus.LOCKED,
            difficulty=difficulty or "medium",
            created_at=datetime.now(timezone.utc),
        )
        nodes = list(plan.nodes)
        insert_at = len(nodes) if position is None else max(0, min(position - 1, len(nodes)))
        nodes.insert(insert_at, new_node)
        await self._repository.replace_nodes(plan.id, self._ensure_startable(nodes))
        return await self._repository.get(plan_id) or plan

    async def add_problem_step(self, plan_id: str, problem_id: str) -> LessonPlan:
        """Appends a step that serves one problem the learner ALREADY has — how an existing
        question gets somewhere they can work it. Skill and difficulty come off the problem,
        so nothing is generated and nothing is asked of the LLM."""
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
                # ensure_skill takes a NAME, so the title is the only sane fallback for a
                # problem stored without skills.
                else await self._skill_repository.ensure_skill(problem.title)
            ),
            sequence_index=0,  # reindexed below
            # AVAILABLE, not LOCKED: the learner named this problem, and it is one they
            # already have, so there is no prerequisite to gate it behind.
            status=LessonNodeStatus.AVAILABLE,
            difficulty=problem.difficulty,
            problem_id=problem.id,
            created_at=datetime.now(timezone.utc),
        )
        await self._repository.replace_nodes(
            plan.id, self._ensure_startable([*plan.nodes, new_node])
        )
        return await self._repository.get(plan_id) or plan

    async def remove_step(self, plan_id: str, step: str) -> LessonPlan:
        """Drops one step. Refuses to remove a completed one — matching the rest of this
        file, finished work is never silently discarded. replace_nodes already cascades the
        dropped node's problem session (see its docstring)."""
        plan = await self._require_plan(plan_id)
        target = self._resolve_step(plan, step)
        if target.status == LessonNodeStatus.DONE:
            raise NotFoundError("Can't remove a completed step")
        nodes = [node for node in plan.nodes if node.id != target.id]
        await self._repository.replace_nodes(plan.id, self._ensure_startable(nodes))
        return await self._repository.get(plan_id) or plan

    async def reorder_step(self, plan_id: str, step: str, to_position: int) -> LessonPlan:
        """Moves one step to a new position. The step's own problem is still exactly as
        valid as it was — nothing about what it should contain changed — so no session is
        invalidated."""
        plan = await self._require_plan(plan_id)
        target = self._resolve_step(plan, step)
        nodes = [node for node in plan.nodes if node.id != target.id]
        insert_at = max(0, min(to_position - 1, len(nodes)))
        nodes.insert(insert_at, target)
        await self._repository.replace_nodes(plan.id, self._ensure_startable(nodes))
        return await self._repository.get(plan_id) or plan

    async def edit_plan(self, plan_id: str, instruction: str) -> LessonPlan:
        """Applies a free-text revision ("add a step on hash maps", "make step 3 harder",
        "redo the whole thing") to an existing plan. Steps the revision leaves alone keep
        their identity — and therefore their DONE status and problem sessions — so editing
        a plan never costs the learner finished work. A step whose difficulty the revision
        actually changed has its not-yet-submitted problem session invalidated (see
        _invalidate_unsubmitted), so "make step 3 harder" regenerates step 3's problem
        instead of leaving the old, now-mismatched one in place."""
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

        # Match revised steps back onto existing nodes by skill name — an exact (normalized)
        # match means "this step was untouched", so it keeps its row and its progress.
        existing_by_skill: dict[str, list[LessonNode]] = {}
        for node in plan.nodes:
            existing_by_skill.setdefault((node.skill_name or "").strip().lower(), []).append(node)

        nodes: list[LessonNode] = []
        matched_ids: set[str] = set()
        # A matched node keeps its row (and therefore its problem session) — but if the
        # revision actually changed its difficulty, the session that was already selected or
        # started no longer matches what the step is supposed to be, and must regenerate.
        redifficultied_ids: set[str] = set()
        seen_skills: set[str] = set()
        for step in revised.steps:
            skill_key = step.skill.strip().lower()
            # Without this a repeated skill falls through to creating a second node for it.
            if skill_key in seen_skills:
                continue
            seen_skills.add(skill_key)
            candidates = existing_by_skill.get(skill_key, [])
            match = next((c for c in candidates if c.id not in matched_ids), None)
            # Already easy/medium/hard — the revision schema speaks the same vocabulary the
            # plan stores, so an untouched step's difficulty round-trips unchanged.
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
                        sequence_index=0,  # reindexed below
                        status=LessonNodeStatus.LOCKED,
                        difficulty=difficulty,
                        created_at=datetime.now(timezone.utc),
                    )
                )

        # Completed work is never discarded, even if the revision dropped it. Finished steps
        # keep their original relative order at the front of the plan.
        rescued = sorted(
            (n for n in plan.nodes if n.status == LessonNodeStatus.DONE and n.id not in matched_ids),
            key=lambda n: n.sequence_index,
        )
        nodes = rescued + nodes

        await self._repository.replace_nodes(plan.id, self._ensure_startable(nodes))
        await self._invalidate_unsubmitted(redifficultied_ids)
        return await self._repository.get(plan.id) or plan

    async def get_node_notes(
        self, node_id: str, refresh: bool = False
    ) -> GeneratedLessonNotes:
        """Lesson for the problem the node is serving, generated on request and cached
        after. Locked nodes are refused so lessons can't be generated (and paid for) ahead
        of the curriculum. refresh forces a fresh generation over the cached one.

        The problem is passed in so the lesson teaches the mechanic that actually solves
        it rather than a loose association with the skill name. It is genuinely optional:
        the notes tab can be opened before the learner presses Start, and a skill-only
        lesson is still worth having then."""
        node = await self._repository.get_node(node_id)
        if node is None:
            raise NotFoundError(f"Lesson node {node_id} not found")
        if node.status == LessonNodeStatus.LOCKED:
            raise NotFoundError(
                f"Lesson notes for node {node_id} are not available until it is unlocked"
            )

        plan = await self._repository.get(node.lesson_plan_id)
        if plan is None:
            raise NotFoundError(f"Lesson plan {node.lesson_plan_id} not found")

        problem = version = None
        if self._problem_session_repository is not None and self._problem_repository is not None:
            session = await self._problem_session_repository.get_by_node(node_id)
            if session is not None:
                problem = await self._problem_repository.get(session.problem_id)
                version = await self._problem_repository.get_latest_version(session.problem_id)

        # ponytail: lessons live in llm_cache keyed by (problem or skill, language, level)
        # — they're derivable and cheap to regenerate, so they need no table of their own.
        # Give them one only if they ever become user-editable or per-user personalized, at
        # which point they stop being derivable.
        return await generate_lesson_notes(
            self._llm_provider,
            # The skills JOIN is INNER so skill_name is always present; the fallback only
            # satisfies the str | None type (a raw UUID here would poison the cache key).
            node.skill_name or node.skill_id,
            plan.language.value,
            plan.level,
            cache=self._llm_cache,
            refresh=refresh,
            problem_id=problem.id if problem else None,
            problem_title=problem.title if problem else None,
            tags=problem.tags if problem else None,
            statement_md=version.statement_md if version else None,
            reference_solution=version.reference_solution if version else None,
        )

    async def list_for_session(self, session_id: str) -> list[LessonPlan]:
        return await self._repository.list_for_session(session_id)

