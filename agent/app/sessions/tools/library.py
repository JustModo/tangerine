import logging
from collections.abc import AsyncIterator

from app.curriculum.application.problem_sessions import ProblemSessionService
from app.curriculum.application.services import CurriculumService
from app.curriculum.domain.models import LessonPlan
from app.llm.domain.requests import ToolDeclaration
from app.llm.prompts.tools import (
    CREATE_PRACTICE_PLAN_TOOL,
    FIND_PROBLEMS_TOOL,
    SET_PROBLEM_FLAG_TOOL,
)
from app.problems.application.library import ProblemLibraryService
from app.sessions.application import plan_edits
from app.sessions.application.tool_results import library_context, library_memo
from app.sessions.tools.base import ToolCallContext, ToolLabel, ToolResult
from app.shared.errors import NotFoundError

logger = logging.getLogger(__name__)


class FindProblemsTool:
    def __init__(
        self,
        library_service: ProblemLibraryService | None = None,
        problem_session_service: ProblemSessionService | None = None,
    ) -> None:
        self._library_service = library_service
        self._problem_session_service = problem_session_service

    @property
    def declaration(self) -> ToolDeclaration:
        return FIND_PROBLEMS_TOOL

    def is_available(self, plan: LessonPlan | None, user_id: str | None) -> bool:
        return (
            self._library_service is not None
            and self._problem_session_service is not None
            and bool(user_id)
        )

    async def execute(self, ctx: ToolCallContext) -> AsyncIterator[ToolLabel | ToolResult]:
        yield ToolLabel("Looking through your problems...")

        args, user_id = ctx.args, ctx.user_id
        scope = (args.get("scope") or "all").strip().lower()
        entries, stats = [], None
        if self._library_service is not None and user_id:
            try:
                entries = await self._library_service.find(
                    user_id,
                    query=(args.get("query") or "").strip() or None,
                    scope=scope,
                    skill=(args.get("skill") or "").strip() or None,
                    language=(args.get("language") or "").strip().lower() or None,
                )
                stats = await self._library_service.stats(user_id)
            except Exception:
                logger.warning("Problem lookup failed for %s", user_id, exc_info=True)

        yield ToolResult(
            tool_name="find_problems",
            summary=library_context(entries, scope, stats),
            fallback=(
                "Here's what I found — want me to put one on your plan?"
                if entries
                else "I couldn't find anything matching that. Want me to make you a new one?"
            ),
            memo=library_memo(entries),
            instruction=(
                "Answer their question from this list. Name problems by TITLE and never "
                "read an id out loud. Do not mention any problem that is not on the list, "
                "and do not invent one. If they want to work on one, offer to add it to "
                "their plan — this chat builds plans, it does not open problems."
            ),
        )


class CreatePracticePlanTool:
    def __init__(
        self,
        curriculum_service: CurriculumService | None = None,
        library_service: ProblemLibraryService | None = None,
    ) -> None:
        self._curriculum_service = curriculum_service
        self._library_service = library_service

    @property
    def declaration(self) -> ToolDeclaration:
        return CREATE_PRACTICE_PLAN_TOOL

    def is_available(self, plan: LessonPlan | None, user_id: str | None) -> bool:
        return (
            self._library_service is not None
            and self._curriculum_service is not None
            and bool(user_id)
        )

    async def execute(self, ctx: ToolCallContext) -> AsyncIterator[ToolLabel | ToolResult]:
        problem_ids = [str(value) for value in (ctx.args.get("problem_ids") or []) if value]
        topic = (ctx.args.get("topic") or "Revision").strip() or "Revision"

        if not problem_ids:
            yield ToolResult(
                tool_name="create_practice_plan",
                summary=(
                    "NOT RUN — no problems were given, so no plan was built. Ask which "
                    "problems they want in it."
                ),
                fallback="Which problems should I put in it?",
            )
            return

        yield ToolLabel(f"Building a plan from {len(problem_ids)} problem(s)...", persist=True)

        plan = None
        not_run: NotFoundError | None = None
        if self._curriculum_service is not None:
            try:
                plan = await self._curriculum_service.create_practice_plan(
                    ctx.session_id, problem_ids, topic
                )
            except NotFoundError as exc:
                not_run = exc
            except Exception:
                logger.warning("Practice plan failed for session %s", ctx.session_id, exc_info=True)

        if plan is not None:
            summary = (
                f"Built a {len(plan.nodes)}-step plan out of problems they already have. "
                "Each step reopens that exact problem. " + plan_edits.plan_step_summary(plan)
            )
            fallback = f"Built you a {len(plan.nodes)}-step plan from those problems."
        elif not_run is not None:
            summary = f"NOT RUN — {not_run} Tell the user and offer to find the problems again."
            fallback = "I couldn't build that plan — want me to look up those problems again?"
        else:
            summary = "Plan build failed — tell the user something went wrong."
            fallback = "Something went wrong building that plan — want me to try again?"

        yield ToolResult(
            tool_name="create_practice_plan",
            summary=summary,
            fallback=fallback,
            plan_id=plan.id if plan is not None else None,
        )


class SetProblemFlagTool:
    def __init__(
        self,
        problem_session_service: ProblemSessionService | None = None,
        library_service: ProblemLibraryService | None = None,
    ) -> None:
        self._problem_session_service = problem_session_service
        self._library_service = library_service

    @property
    def declaration(self) -> ToolDeclaration:
        return SET_PROBLEM_FLAG_TOOL

    def is_available(self, plan: LessonPlan | None, user_id: str | None) -> bool:
        return (
            self._library_service is not None
            and self._problem_session_service is not None
            and bool(user_id)
        )

    async def execute(self, ctx: ToolCallContext) -> AsyncIterator[ToolLabel | ToolResult]:
        user_id = ctx.user_id
        problem_id = (ctx.args.get("problem_id") or "").strip()
        flagged = bool(ctx.args.get("flagged"))
        yield ToolLabel("Flagging that problem..." if flagged else "Clearing that flag...")

        ok = False
        if self._problem_session_service is not None and user_id and problem_id:
            try:
                await self._problem_session_service.set_flagged_for_problem(
                    user_id, problem_id, flagged
                )
                ok = True
            except Exception:
                logger.warning("Could not flag problem %s", problem_id, exc_info=True)

        verb = "Flagged" if flagged else "Unflagged"
        yield ToolResult(
            tool_name="set_problem_flag",
            summary=(
                f"{verb} that problem."
                if ok
                else "NOT RUN — the flag could not be changed. Tell the user plainly."
            ),
            fallback=(
                f"{verb} it for you."
                if ok
                else "I couldn't change that flag — want me to try again?"
            ),
        )
