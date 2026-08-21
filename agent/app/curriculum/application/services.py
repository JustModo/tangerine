import uuid
from datetime import datetime, timezone

from app.curriculum.domain.models import LessonNode, LessonNodeStatus, LessonPlan, LessonPlanStatus
from app.curriculum.domain.repository import LessonPlanRepository
from app.llm.domain.provider import LLMProvider
from app.llm.graphs.curriculum import generate_curriculum
from app.llm.infrastructure.cache import SqliteLLMCache
from app.problems.infrastructure.sqlite_skill_repository import SqliteSkillRepository
from app.shared.errors import NotFoundError
from app.shared.types import Language


class CurriculumService:
    """Draft/accept lifecycle for lesson plans (plan.md §59-60, §74). A draft's nodes are
    populated immediately via the curriculum LangGraph (plan.md §22/76 Graph B)."""

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
        self, session_id: str, topic: str, language: Language, level: str
    ) -> LessonPlan:
        plan = LessonPlan(
            id=str(uuid.uuid4()),
            session_id=session_id,
            topic=topic,
            language=language,
            level=level,
            status=LessonPlanStatus.DRAFT,
            version=1,
            created_at=datetime.now(timezone.utc),
        )
        await self._repository.save(plan)

        generated = await generate_curriculum(
            self._llm_provider, topic, language.value, level, cache=self._llm_cache
        )
        nodes = []
        for index, generated_node in enumerate(generated.nodes):
            skill_id = await self._skill_repository.ensure_skill(generated_node.skill)
            nodes.append(
                LessonNode(
                    id=str(uuid.uuid4()),
                    lesson_plan_id=plan.id,
                    skill_id=skill_id,
                    sequence_index=index,
                    status=LessonNodeStatus.AVAILABLE if index == 0 else LessonNodeStatus.LOCKED,
                    created_at=datetime.now(timezone.utc),
                )
            )
        if nodes:
            await self._repository.save_nodes(nodes)

        return await self._repository.get(plan.id) or plan

    async def get(self, plan_id: str) -> LessonPlan | None:
        return await self._repository.get(plan_id)

    async def accept(self, plan_id: str) -> LessonPlan:
        plan = await self._repository.get(plan_id)
        if plan is None:
            raise NotFoundError(f"Lesson plan {plan_id} not found")

        for sibling in await self._repository.list_for_session(plan.session_id):
            if sibling.id != plan.id and sibling.status == LessonPlanStatus.ACCEPTED:
                superseded = sibling.model_copy(update={"status": LessonPlanStatus.SUPERSEDED})
                await self._repository.save(superseded)

        accepted = plan.model_copy(update={"status": LessonPlanStatus.ACCEPTED})
        await self._repository.save(accepted)
        return accepted
