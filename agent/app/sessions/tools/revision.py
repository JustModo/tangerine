import logging
from collections.abc import AsyncIterator

from app.curriculum.domain.models import LessonPlan
from app.llm.domain.requests import ToolDeclaration
from app.llm.prompts.tools import PRACTICE_RECORD_TOOL
from app.problems.application.library import ProblemLibraryService
from app.revision.application.services import RevisionService
from app.sessions.application.tool_results import mastery_context
from app.sessions.tools.base import ToolCallContext, ToolLabel, ToolResult

logger = logging.getLogger(__name__)


class PracticeRecordTool:
    def __init__(
        self,
        revision_service: RevisionService | None = None,
        library_service: ProblemLibraryService | None = None,
    ) -> None:
        self._revision_service = revision_service
        self._library_service = library_service

    @property
    def declaration(self) -> ToolDeclaration:
        return PRACTICE_RECORD_TOOL

    def is_available(self, plan: LessonPlan | None, user_id: str | None) -> bool:
        return self._revision_service is not None and bool(user_id)

    async def execute(self, ctx: ToolCallContext) -> AsyncIterator[ToolLabel | ToolResult]:
        yield ToolLabel("Checking your progress...")

        user_id = ctx.user_id
        candidates = []
        if self._revision_service is not None and user_id:
            try:
                candidates = await self._revision_service.get_revision_queue(user_id)
            except Exception:
                logger.warning("Failed to load the practice record for %s", user_id, exc_info=True)

        record = mastery_context(candidates)
        if self._library_service is not None and user_id:
            try:
                stats = await self._library_service.stats(user_id)
                record += (
                    f"\n- Totals: {stats.solved_total} problems solved all time, "
                    f"{stats.solved_this_week} in the last 7 days, best streak "
                    f"{stats.best_streak}."
                )
            except Exception:
                logger.warning("Failed to load totals for %s", user_id, exc_info=True)

        yield ToolResult(
            tool_name="get_practice_record",
            summary=record,
            fallback=(
                "Here's where you're at — want me to build a plan around one of these?"
                if candidates
                else "You haven't finished any practice problems yet, so I've nothing to go on. "
                "What would you like to work on?"
            ),
            instruction=(
                "Answer their question from it: name the two or three topics worth their time, "
                "a few words on why each, then ask if they want a plan for one. Use the skill "
                "names exactly as given and do not invent any. Do not read the scores out as "
                "numbers."
            ),
        )
