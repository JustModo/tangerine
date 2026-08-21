import uuid
from datetime import datetime, timezone

from app.curriculum.domain.models import LessonNode, LessonNodeStatus, LessonPlan
from app.curriculum.domain.repository import LessonPlanRepository
from app.llm.domain.provider import LLMProvider
from app.llm.graphs.curriculum import generate_curriculum
from app.llm.graphs.lesson_notes import generate_lesson_notes
from app.llm.graphs.plan_edit import revise_curriculum
from app.llm.infrastructure.cache import SqliteLLMCache
from app.llm.schemas.lesson_notes import GeneratedLessonNotes
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.shared.errors import NotFoundError
from app.shared.types import Language


# The curriculum LLM rates each step 1-5; problem selection speaks easy/medium/hard.
_DIFFICULTY_BY_RATING = {1: "easy", 2: "easy", 3: "medium", 4: "hard", 5: "hard"}


def _difficulty_label(rating: int) -> str:
    return _DIFFICULTY_BY_RATING.get(rating, "medium")


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
    ) -> None:
        self._repository = repository
        self._llm_provider = llm_provider
        self._skill_repository = skill_repository or SqliteSkillRepository()
        self._llm_cache = llm_cache

    async def create_draft(
        self,
        session_id: str,
        topic: str,
        language: Language,
        level: str,
        step_count: int | None = None,
        target_problem: str | None = None,
    ) -> LessonPlan:
        """step_count honours an explicit "just 2 lessons" request; target_problem is a
        question the learner pasted in, in which case the generated steps are prerequisites
        and one extra final step is appended that serves that exact problem."""
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
        # problem" therefore means ZERO prerequisites, and we skip curriculum generation
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
            )
            generated_nodes = generated.nodes

        nodes = []
        for index, generated_node in enumerate(generated_nodes):
            skill_id = await self._skill_repository.ensure_skill(generated_node.skill)
            nodes.append(
                LessonNode(
                    id=str(uuid.uuid4()),
                    lesson_plan_id=plan.id,
                    skill_id=skill_id,
                    sequence_index=index,
                    status=LessonNodeStatus.AVAILABLE if index == 0 else LessonNodeStatus.LOCKED,
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
                    status=LessonNodeStatus.AVAILABLE if not nodes else LessonNodeStatus.LOCKED,
                    difficulty="hard",
                    source_problem_md=target_problem,
                    created_at=datetime.now(timezone.utc),
                )
            )

        if nodes:
            await self._repository.save_nodes(nodes)

        return await self._repository.get(plan.id) or plan

    async def get(self, plan_id: str) -> LessonPlan | None:
        return await self._repository.get(plan_id)

    async def edit_plan(self, plan_id: str, instruction: str) -> LessonPlan:
        """Applies a free-text revision ("add a step on hash maps", "make step 3 harder",
        "redo the whole thing") to an existing plan. Steps the revision leaves alone keep
        their identity — and therefore their DONE status and problem sessions — so editing
        a plan never costs the learner finished work."""
        plan = await self._repository.get(plan_id)
        if plan is None:
            raise NotFoundError(f"Lesson plan {plan_id} not found")

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
        for step in revised.steps:
            candidates = existing_by_skill.get(step.skill.strip().lower(), [])
            match = next((c for c in candidates if c.id not in matched_ids), None)
            # Already easy/medium/hard — the revision schema speaks the same vocabulary the
            # plan stores, so an untouched step's difficulty round-trips unchanged.
            difficulty = step.difficulty
            if match is not None:
                matched_ids.add(match.id)
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

        ordered = [node.model_copy(update={"sequence_index": index}) for index, node in enumerate(nodes)]
        # Keep the plan startable: the first unfinished step must never be left LOCKED.
        for index, node in enumerate(ordered):
            if node.status != LessonNodeStatus.DONE:
                if node.status == LessonNodeStatus.LOCKED:
                    ordered[index] = node.model_copy(update={"status": LessonNodeStatus.AVAILABLE})
                break

        await self._repository.replace_nodes(plan.id, ordered)
        return await self._repository.get(plan.id) or plan

    async def get_node_notes(self, node_id: str) -> GeneratedLessonNotes:
        """Teaching cheat sheet for a node's skill, generated on first read and cached
        forever after. Locked nodes are refused so notes can't be generated (and paid for)
        ahead of the curriculum."""
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

        # ponytail: notes live in llm_cache keyed by (skill, language, level) — they're
        # derivable, shared across every plan, and cheap to regenerate, so they need no
        # table of their own. Give them one only if they ever become user-editable or
        # per-user personalized, at which point they stop being derivable.
        return await generate_lesson_notes(
            self._llm_provider,
            # The skills JOIN is INNER so skill_name is always present; the fallback only
            # satisfies the str | None type (a raw UUID here would poison the cache key).
            node.skill_name or node.skill_id,
            plan.language.value,
            plan.level,
            cache=self._llm_cache,
        )

    async def list_for_session(self, session_id: str) -> list[LessonPlan]:
        return await self._repository.list_for_session(session_id)

