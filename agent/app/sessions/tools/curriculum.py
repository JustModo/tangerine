import logging
from collections.abc import AsyncIterator

from app.curriculum.application.services import CurriculumService
from app.curriculum.domain.models import LessonNodeStatus, LessonPlan
from app.llm.domain.requests import ToolDeclaration
from app.llm.prompts.tools import EDIT_PLAN_TOOL, GENERATE_PLAN_TOOL, GET_PLAN_TOOL
from app.sessions.application import plan_edits
from app.sessions.application.tool_results import plan_context, step_problem_context
from app.sessions.tools.base import ToolCallContext, ToolLabel, ToolResult
from app.shared.errors import AgentError, ConflictError, NotFoundError
from app.shared.preferences import get_preferences
from app.shared.types import SUPPORTED_LANGUAGES, Language

logger = logging.getLogger(__name__)


async def _resolve_language(requested_language: str) -> Language | None:
    if requested_language:
        try:
            return Language(requested_language)
        except ValueError:
            return None
    default = (await get_preferences())["default_language"]
    return Language(default) if default != "ask" else None


class GeneratePlanTool:
    def __init__(self, curriculum_service: CurriculumService | None = None) -> None:
        self._curriculum_service = curriculum_service

    @property
    def declaration(self) -> ToolDeclaration:
        return GENERATE_PLAN_TOOL

    def is_available(self, plan: LessonPlan | None, user_id: str | None) -> bool:
        return True

    async def execute(self, ctx: ToolCallContext) -> AsyncIterator[ToolLabel | ToolResult]:
        requested_language = (ctx.args.get("language") or "").strip().lower()
        language = await _resolve_language(requested_language)
        if language is None:
            supported = ", ".join(SUPPORTED_LANGUAGES)
            if requested_language:
                summary = (
                    f"NOT RUN — '{requested_language}' is not a supported language. No plan "
                    f"was created. Tell the user it isn't supported yet, that the supported "
                    f"languages are {supported}, and ask them to pick one."
                )
                fallback = (
                    f"'{requested_language}' isn't supported yet — I can do {supported}. "
                    "Which would you like?"
                )
            else:
                summary = (
                    "NOT RUN — the user has not said which programming language they want. "
                    f"No plan was created. Ask them which of {supported} they want, in one "
                    "short question, and do not imply anything was built."
                )
                fallback = f"Which language would you like to practice in? I support {supported}."
            yield ToolResult(
                tool_name="generate_learning_plan", summary=summary, fallback=fallback
            )
            return

        yield ToolLabel(
            "Updating your learning plan..." if ctx.active_plan else "Generating a learning plan...",
            persist=True,
        )

        topic = ctx.args.get("topic") or "this topic"
        level = ctx.args.get("level") or "beginner"
        step_count = ctx.args.get("step_count")
        target_problem = ctx.args.get("target_problem") or None

        plan = None
        if self._curriculum_service is not None:
            try:
                plan = await self._curriculum_service.create_draft(
                    ctx.session_id,
                    topic,
                    language,
                    level,
                    step_count=int(step_count) if step_count else None,
                    target_problem=target_problem,
                    user_id=ctx.user_id,
                )
            except Exception:
                logger.warning(
                    "Plan generation failed for session %s", ctx.session_id, exc_info=True
                )

        if plan is not None:
            skipped = sum(1 for node in plan.nodes if node.status == LessonNodeStatus.DONE)
            summary = f"Generated a learning plan for '{plan.topic}' with {len(plan.nodes)} steps."
            if skipped:
                summary += (
                    f" {skipped} of them are already marked done because their practice "
                    "record shows they've mastered those skills — mention this."
                )
            fallback = "Your learning plan is ready — check the corner button to view it."
        else:
            summary = (
                "Plan generation failed — tell the user something went wrong and they can try again."
            )
            fallback = "Something went wrong generating the plan — want to try again?"

        yield ToolResult(
            tool_name="generate_learning_plan",
            summary=summary,
            fallback=fallback,
            plan_id=plan.id if plan is not None else None,
        )


class EditPlanTool:
    def __init__(self, curriculum_service: CurriculumService | None = None) -> None:
        self._curriculum_service = curriculum_service

    @property
    def declaration(self) -> ToolDeclaration:
        return EDIT_PLAN_TOOL

    def is_available(self, plan: LessonPlan | None, user_id: str | None) -> bool:
        return plan is not None

    async def execute(self, ctx: ToolCallContext) -> AsyncIterator[ToolLabel | ToolResult]:
        operation = ctx.args.get("operation") or "rework"
        active_plan = ctx.active_plan

        if active_plan is None:
            yield ToolResult(
                tool_name="edit_learning_plan",
                summary=(
                    "NOT RUN — there is no plan for this session to edit. Tell the user "
                    "something went wrong and they can try again."
                ),
                fallback="I couldn't find a plan to edit — want to try again?",
            )
            return

        outcome = plan_edits.build(
            operation, ctx.args, active_plan.id, self._curriculum_service, ctx.message
        )
        if isinstance(outcome, plan_edits.Refusal):
            yield ToolResult(
                tool_name="edit_learning_plan",
                summary=outcome.summary,
                fallback=outcome.fallback,
            )
            return

        yield ToolLabel(outcome.label, persist=True)

        plan = None
        not_run: AgentError | None = None
        try:
            plan = await outcome.action()
        except (NotFoundError, ConflictError) as exc:
            not_run = exc
        except Exception:
            logger.warning(
                "Plan edit (%s) failed for session %s", operation, ctx.session_id, exc_info=True
            )

        if plan is not None:
            summary = outcome.done_text(plan)
            fallback = "Updated your plan — open it with the corner button to see the changes."
        elif not_run is not None:
            summary = (
                f"NOT RUN — {not_run}. Nothing was changed. Tell the user this plainly and "
                "ask them to clarify or try something else."
            )
            fallback = f"{not_run} — want to try something else?"
        else:
            summary = (
                "Plan edit failed — tell the user something went wrong and they can try again."
            )
            fallback = "Something went wrong updating the plan — want to try again?"

        yield ToolResult(
            tool_name="edit_learning_plan",
            summary=summary,
            fallback=fallback,
            plan_id=plan.id if plan is not None else None,
            active_plan=plan if plan is not None else active_plan,
        )


class GetPlanTool:
    def __init__(self, curriculum_service: CurriculumService | None = None) -> None:
        self._curriculum_service = curriculum_service

    @property
    def declaration(self) -> ToolDeclaration:
        return GET_PLAN_TOOL

    def is_available(self, plan: LessonPlan | None, user_id: str | None) -> bool:
        return plan is not None

    async def execute(self, ctx: ToolCallContext) -> AsyncIterator[ToolLabel | ToolResult]:
        step = str(ctx.args.get("step") or "").strip()
        yield ToolLabel(f"Reading step {step}..." if step else "Reading your plan...")

        summary = plan_context(ctx.active_plan)
        if step and ctx.active_plan is not None and self._curriculum_service is not None:
            try:
                node, problem = await self._curriculum_service.step_problem(ctx.active_plan.id, step)
                summary += f"\n\n{step_problem_context(node, problem)}"
            except (NotFoundError, ConflictError) as exc:
                summary += f"\n\nCould not read step '{step}': {exc}. Do not describe it."
            except Exception:
                logger.warning("Step lookup failed for %s", ctx.session_id, exc_info=True)

        yield ToolResult(
            tool_name="get_learning_plan",
            summary=summary,
            fallback="I couldn't read your plan just then — want me to try again?",
            memo=summary,
            instruction=(
                "Answer their question from this and nothing else. Use the step numbers "
                "and names exactly as given, and never describe a step, a question or a "
                "test case that is not shown above."
            ),
        )
