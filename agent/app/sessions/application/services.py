import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from app.curriculum.application.services import CurriculumService
from app.curriculum.domain.models import LessonNodeStatus, LessonPlan
from app.llm.domain.provider import LLMProvider
from app.llm.domain.requests import ChatStreamRequest, ChatTurn
from app.llm.prompts.chat import (
    CREATE_PRACTICE_PLAN_TOOL,
    EDIT_PLAN_TOOL,
    FIND_PROBLEMS_TOOL,
    GENERATE_PLAN_TOOL,
    GET_PLAN_TOOL,
    PRACTICE_RECORD_TOOL,
    SET_PROBLEM_FLAG_TOOL,
    SUPPORTED_LANGUAGES,
    chat_system_prompt,
)
from app.revision.application.services import RevisionService
from app.sessions.application import plan_edits
from app.sessions.application.tool_registry import ToolContext, ToolSpec
from app.sessions.application.tool_results import (
    library_context,
    library_memo,
    mastery_context,
    plan_context,
    step_problem_context,
)
from app.sessions.domain.models import ChatMessage, ChatRole, LearningSession, SessionStatus
from app.sessions.domain.repository import SessionRepository
from app.shared.errors import AgentError, ConflictError, NotFoundError
from app.shared.preferences import get_preferences
from app.shared.types import Language

logger = logging.getLogger(__name__)

MAX_HISTORY_TURNS = 20
MAX_TOOL_CHAIN = 2


class SessionService:
    """Service managing chat sessions and LLM tool execution."""

    def __init__(
        self,
        repository: SessionRepository,
        llm_provider: LLMProvider | None = None,
        curriculum_service: CurriculumService | None = None,
        revision_service: RevisionService | None = None,
        problem_session_service=None,
        library_service=None,
    ) -> None:
        self._repository = repository
        self._llm_provider = llm_provider
        self._curriculum_service = curriculum_service
        self._revision_service = revision_service
        self._problem_session_service = problem_session_service
        self._library_service = library_service

    async def create_session(self, user_id: str) -> LearningSession:
        now = datetime.now(UTC)
        session = LearningSession(
            id=str(uuid.uuid4()),
            user_id=user_id,
            status=SessionStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        await self._repository.create(session)
        return session

    async def get_session(self, session_id: str) -> LearningSession | None:
        return await self._repository.get(session_id)

    async def list_sessions(self, user_id: str) -> list[LearningSession]:
        return await self._repository.list_for_user(user_id)

    async def delete_session(self, session_id: str) -> None:
        await self._repository.delete(session_id)

    async def add_message(self, session_id: str, content: str) -> AsyncIterator[dict]:
        """Persist the user message and stream the assistant response events."""
        existing = await self._repository.get(session_id)
        conversation = [
            m
            for m in (existing.messages if existing else [])
            if m.role in (ChatRole.USER, ChatRole.ASSISTANT)
        ][-MAX_HISTORY_TURNS:]
        latest_memo = next(
            (m.id for m in reversed(conversation) if m.role == ChatRole.ASSISTANT and m.intent),
            None,
        )
        history = [
            ChatTurn(
                role="user" if m.role == ChatRole.USER else "assistant",
                content=(
                    f"{m.content}\n\n[tool context — yours to act on, never repeat to the user]\n{m.intent}"
                    if m.id == latest_memo
                    else m.content
                ),
            )
            for m in conversation
        ]

        user_message = ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=ChatRole.USER,
            content=content,
            created_at=datetime.now(UTC),
        )
        await self._repository.add_message(user_message)
        yield {"type": "user_message", "message_id": user_message.id}

        if self._llm_provider is None:
            return

        active_plan = await self._active_plan(session_id)
        user_id = existing.user_id if existing is not None else None
        async for event in self._stream_reply(session_id, history, content, active_plan, user_id):
            yield event

    async def _stream_reply(
        self,
        session_id: str,
        history: list[ChatTurn],
        message: str,
        active_plan: LessonPlan | None,
        user_id: str | None,
        depth: int = 0,
    ) -> AsyncIterator[dict]:
        request = ChatStreamRequest(
            system_prompt=await self._system_prompt(active_plan, user_id),
            history=history,
            message=message,
            tools=self._tools_for(active_plan, user_id),
        )
        text_parts: list[str] = []
        async for chunk in self._llm_provider.stream_chat(request):
            if chunk.text_delta:
                text_parts.append(chunk.text_delta)
                yield {"type": "text_delta", "delta": chunk.text_delta}
            if chunk.tool_call is not None:
                handler = self._handler_for(
                    chunk.tool_call, session_id, history, message, active_plan, user_id, depth
                )
                if handler is not None:
                    async for event in handler:
                        yield event
                    return
            if chunk.done:
                break

        reply_text = "".join(text_parts).strip() or (
            "I didn't manage to put together a reply there. Could you rephrase that?"
        )
        reply = await self._persist_assistant_reply(session_id, reply_text)
        yield {"type": "done", "message_id": reply.id, "content": reply_text}

    async def _active_plan(self, session_id: str) -> LessonPlan | None:
        if self._curriculum_service is None:
            return None
        try:
            plans = await self._curriculum_service.list_for_session(session_id)
        except Exception:
            logger.warning("Plan lookup failed for session %s", session_id, exc_info=True)
            return None
        return plans[0] if plans else None

    async def _system_prompt(self, active_plan: LessonPlan | None, user_id: str | None) -> str:
        db_path = getattr(self._repository, "_database_path", None)
        return chat_system_prompt(
            active_plan,
            (await get_preferences(db_path))["default_language"],
            has_record=self._revision_service is not None and bool(user_id),
            has_library=self._library_service is not None and bool(user_id),
        )

    def _tools_for(self, active_plan: LessonPlan | None, user_id: str | None) -> list:
        return [spec.tool for spec in TOOLS if spec.available(self, active_plan, user_id)]

    def _handler_for(
        self,
        tool_call,
        session_id: str,
        history: list[ChatTurn],
        message: str,
        active_plan: LessonPlan | None,
        user_id: str | None,
        depth: int,
        note_id: str | None = None,
    ) -> AsyncIterator[dict] | None:
        spec = _spec_for(tool_call.name)
        if spec is None:
            return None
        return spec.handler(
            self,
            ToolContext(
                session_id=session_id,
                args=tool_call.args,
                history=history,
                message=message,
                active_plan=active_plan,
                user_id=user_id,
                depth=depth,
                note_id=note_id,
            ),
        )

    async def _announce(self, session_id: str, label: str, note_id: str | None) -> dict:
        if note_id is not None:
            await self._repository.update_message_content(note_id, label)
        else:
            note = ChatMessage(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role=ChatRole.SYSTEM,
                content=label,
                created_at=datetime.now(UTC),
            )
            await self._repository.add_message(note)
            note_id = note.id
        return {"type": "tool_start", "label": label, "message_id": note_id}

    async def _resolve_language(self, requested_language: str) -> Language | None:
        if requested_language:
            try:
                return Language(requested_language)
            except ValueError:
                return None
        default = (await get_preferences())["default_language"]
        return Language(default) if default != "ask" else None

    async def _handle_generate_plan(self, call: ToolContext) -> AsyncIterator[dict]:
        requested_language = (call.args.get("language") or "").strip().lower()
        language = await self._resolve_language(requested_language)
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
            async for event in self._refuse(call, "generate_learning_plan", summary, fallback):
                yield event
            return

        label = (
            "Updating your learning plan..." if call.active_plan else "Generating a learning plan..."
        )
        event = await self._announce(call.session_id, label, call.note_id)
        note_id = event["message_id"]
        yield event

        topic = call.args.get("topic") or "this topic"
        level = call.args.get("level") or "beginner"
        step_count = call.args.get("step_count")
        target_problem = call.args.get("target_problem") or None

        plan = None
        if self._curriculum_service is not None:
            try:
                plan = await self._curriculum_service.create_draft(
                    call.session_id,
                    topic,
                    language,
                    level,
                    step_count=int(step_count) if step_count else None,
                    target_problem=target_problem,
                    user_id=call.user_id,
                )
            except Exception:
                logger.warning(
                    "Plan generation failed for session %s", call.session_id, exc_info=True
                )

        if plan is not None:
            skipped = sum(1 for node in plan.nodes if node.status == LessonNodeStatus.DONE)
            result_summary = f"Generated a learning plan for '{plan.topic}' with {len(plan.nodes)} steps."
            if skipped:
                result_summary += (
                    f" {skipped} of them are already marked done because their practice "
                    "record shows they've mastered those skills — mention this."
                )
        else:
            result_summary = (
                "Plan generation failed — tell the user something went wrong and they can try again."
            )
        fallback = (
            "Your learning plan is ready — check the corner button to view it."
            if plan is not None
            else "Something went wrong generating the plan — want to try again?"
        )
        async for event in self._followup(
            call,
            "generate_learning_plan",
            result_summary,
            fallback,
            plan.id if plan is not None else None,
            note_id=note_id,
        ):
            yield event

    def _followup(
        self,
        call: ToolContext,
        tool_name: str,
        result_summary: str,
        fallback_text: str,
        plan_id: str | None = None,
        *,
        active_plan: LessonPlan | None = None,
        instruction: str | None = None,
        memo: str | None = None,
        note_id: str | None = None,
    ) -> AsyncIterator[dict]:
        extra = {} if instruction is None else {"instruction": instruction}
        return self._stream_tool_followup(
            call.session_id,
            call.history,
            call.message,
            call.active_plan if active_plan is None else active_plan,
            call.user_id,
            tool_name,
            result_summary,
            fallback_text,
            plan_id,
            memo=memo,
            depth=call.depth,
            note_id=call.note_id if note_id is None else note_id,
            **extra,
        )

    def _refuse(
        self, call: ToolContext, tool_name: str, summary: str, fallback: str
    ) -> AsyncIterator[dict]:
        return self._followup(call, tool_name, summary, fallback)

    async def _handle_edit_plan(self, call: ToolContext) -> AsyncIterator[dict]:
        operation = call.args.get("operation") or "rework"

        active_plan = await self._active_plan(call.session_id)
        if active_plan is None:
            async for event in self._refuse(
                call,
                "edit_learning_plan",
                "NOT RUN — there is no plan for this session to edit. Tell the user "
                "something went wrong and they can try again.",
                "I couldn't find a plan to edit — want to try again?",
            ):
                yield event
            return

        outcome = plan_edits.build(
            operation, call.args, active_plan.id, self._curriculum_service, call.message
        )
        if isinstance(outcome, plan_edits.Refusal):
            async for event in self._refuse(
                call, "edit_learning_plan", outcome.summary, outcome.fallback
            ):
                yield event
            return

        event = await self._announce(call.session_id, outcome.label, call.note_id)
        note_id = event["message_id"]
        yield event

        plan = None
        not_run: AgentError | None = None
        try:
            plan = await outcome.action()
        except (NotFoundError, ConflictError) as exc:
            not_run = exc
        except Exception:
            logger.warning(
                "Plan edit (%s) failed for session %s", operation, call.session_id, exc_info=True
            )

        if plan is not None:
            result_summary = outcome.done_text(plan)
            fallback = "Updated your plan — open it with the corner button to see the changes."
        elif not_run is not None:
            result_summary = (
                f"NOT RUN — {not_run}. Nothing was changed. Tell the user this plainly and "
                "ask them to clarify or try something else."
            )
            fallback = f"{not_run} — want to try something else?"
        else:
            result_summary = "Plan edit failed — tell the user something went wrong and they can try again."
            fallback = "Something went wrong updating the plan — want to try again?"

        async for event in self._followup(
            call,
            "edit_learning_plan",
            result_summary,
            fallback,
            plan.id if plan is not None else None,
            active_plan=plan if plan is not None else active_plan,
            note_id=note_id,
        ):
            yield event

    async def _handle_get_plan(self, call: ToolContext) -> AsyncIterator[dict]:
        step = str(call.args.get("step") or "").strip()
        yield {
            "type": "tool_start",
            "label": f"Reading step {step}..." if step else "Reading your plan...",
        }

        summary = plan_context(call.active_plan)
        if step and call.active_plan is not None and self._curriculum_service is not None:
            try:
                node, problem = await self._curriculum_service.step_problem(
                    call.active_plan.id, step
                )
                summary += f"\n\n{step_problem_context(node, problem)}"
            except (NotFoundError, ConflictError) as exc:
                summary += f"\n\nCould not read step '{step}': {exc}. Do not describe it."
            except Exception:
                logger.warning("Step lookup failed for %s", call.session_id, exc_info=True)

        async for event in self._followup(
            call,
            "get_learning_plan",
            summary,
            "I couldn't read your plan just then — want me to try again?",
            instruction=(
                "Answer their question from this and nothing else. Use the step numbers "
                "and names exactly as given, and never describe a step, a question or a "
                "test case that is not shown above."
            ),
            memo=summary,
        ):
            yield event

    async def _handle_practice_record(self, call: ToolContext) -> AsyncIterator[dict]:
        user_id = call.user_id
        yield {"type": "tool_start", "label": "Checking your progress..."}

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

        async for event in self._followup(
            call,
            "get_practice_record",
            record,
            (
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
        ):
            yield event

    async def _handle_find_problems(self, call: ToolContext) -> AsyncIterator[dict]:
        args, user_id = call.args, call.user_id
        yield {"type": "tool_start", "label": "Looking through your problems..."}

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

        async for event in self._followup(
            call,
            "find_problems",
            library_context(entries, scope, stats),
            (
                "Here's what I found — want me to put one on your plan?"
                if entries
                else "I couldn't find anything matching that. Want me to make you a new one?"
            ),
            instruction=(
                "Answer their question from this list. Name problems by TITLE and never "
                "read an id out loud. Do not mention any problem that is not on the list, "
                "and do not invent one. If they want to work on one, offer to add it to "
                "their plan — this chat builds plans, it does not open problems."
            ),
            memo=library_memo(entries),
        ):
            yield event

    async def _handle_create_practice_plan(self, call: ToolContext) -> AsyncIterator[dict]:
        problem_ids = [str(value) for value in (call.args.get("problem_ids") or []) if value]
        topic = (call.args.get("topic") or "Revision").strip() or "Revision"

        if not problem_ids:
            async for event in self._refuse(
                call,
                "create_practice_plan",
                "NOT RUN — no problems were given, so no plan was built. Ask which problems they want in it.",
                "Which problems should I put in it?",
            ):
                yield event
            return

        label = f"Building a plan from {len(problem_ids)} problem(s)..."
        event = await self._announce(call.session_id, label, call.note_id)
        note_id = event["message_id"]
        yield event

        plan = None
        not_run: NotFoundError | None = None
        try:
            plan = await self._curriculum_service.create_practice_plan(
                call.session_id, problem_ids, topic
            )
        except NotFoundError as exc:
            not_run = exc
        except Exception:
            logger.warning("Practice plan failed for session %s", call.session_id, exc_info=True)

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

        async for event in self._followup(
            call,
            "create_practice_plan",
            summary,
            fallback,
            plan.id if plan is not None else None,
            note_id=note_id,
        ):
            yield event

    async def _handle_set_problem_flag(self, call: ToolContext) -> AsyncIterator[dict]:
        user_id = call.user_id
        problem_id = (call.args.get("problem_id") or "").strip()
        flagged = bool(call.args.get("flagged"))
        yield {
            "type": "tool_start",
            "label": "Flagging that problem..." if flagged else "Clearing that flag...",
        }

        ok = False
        if self._problem_session_service is not None and user_id and problem_id:
            try:
                await self._problem_session_service.set_flagged_for_problem(user_id, problem_id, flagged)
                ok = True
            except Exception:
                logger.warning("Could not flag problem %s", problem_id, exc_info=True)

        verb = "Flagged" if flagged else "Unflagged"
        summary = (
            f"{verb} that problem."
            if ok
            else "NOT RUN — the flag could not be changed. Tell the user plainly."
        )
        async for event in self._followup(
            call,
            "set_problem_flag",
            summary,
            f"{verb} it for you." if ok else "I couldn't change that flag — want me to try again?",
        ):
            yield event

    async def _stream_tool_followup(
        self,
        session_id: str,
        history: list[ChatTurn],
        user_message: str,
        active_plan: LessonPlan | None,
        user_id: str | None,
        tool_name: str,
        result_summary: str,
        fallback_text: str,
        plan_id: str | None,
        instruction: str = ("Reply to the user in one or two plain sentences telling them what changed."),
        memo: str | None = None,
        depth: int = 0,
        note_id: str | None = None,
    ) -> AsyncIterator[dict]:
        may_chain = depth + 1 < MAX_TOOL_CHAIN
        chained_context = f"{user_message}\n\n[{tool_name} tool result]\n{result_summary}"
        chain_plan = active_plan
        if may_chain:
            chain_plan = await self._active_plan(session_id)

        follow_up_request = ChatStreamRequest(
            system_prompt=await self._system_prompt(chain_plan, user_id),
            history=history + [ChatTurn(role="user", content=user_message)],
            message=(
                f"[{tool_name} tool result] {result_summary}\n\n"
                f"The tool has ALREADY run and this is its result. {instruction} "
                + (
                    "If the user asked for something this result has not finished — another "
                    "step of the same request — call the tool that finishes it now. "
                    "Otherwise reply in prose and call nothing."
                    if may_chain
                    else "Do not call any tool, and never output JSON, a function call, or code — only prose."
                )
            ),
            tools=(self._tools_for(chain_plan, user_id) if may_chain else []),
        )
        text_parts: list[str] = []
        streamed = 0
        looks_like_tool_call = False
        async for chunk in self._llm_provider.stream_chat(follow_up_request):
            if chunk.text_delta:
                text_parts.append(chunk.text_delta)
                full = "".join(text_parts)
                if full.lstrip().startswith(("{", "```", "[{")):
                    looks_like_tool_call = True
                if not looks_like_tool_call and len(full) > streamed:
                    yield {"type": "text_delta", "delta": full[streamed:]}
                    streamed = len(full)
            if chunk.tool_call is not None and may_chain:
                chained = self._handler_for(
                    chunk.tool_call,
                    session_id,
                    history,
                    chained_context,
                    chain_plan,
                    user_id,
                    depth + 1,
                    note_id,
                )
                if chained is not None:
                    async for event in chained:
                        yield event
                    return
            if chunk.done:
                break

        reply_text = "" if looks_like_tool_call else "".join(text_parts).strip()
        if not reply_text:
            reply_text = fallback_text
        reply = await self._persist_assistant_reply(session_id, reply_text, memo)
        yield {
            "type": "done",
            "message_id": reply.id,
            "content": reply_text,
            "plan_id": plan_id,
        }

    async def _persist_assistant_reply(
        self, session_id: str, content: str, memo: str | None = None
    ) -> ChatMessage:
        reply = ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=ChatRole.ASSISTANT,
            content=content,
            intent=memo,
            created_at=datetime.now(UTC),
        )
        await self._repository.add_message(reply)
        return reply


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(GENERATE_PLAN_TOOL, SessionService._handle_generate_plan, lambda s, plan, uid: True),
    ToolSpec(
        EDIT_PLAN_TOOL, SessionService._handle_edit_plan, lambda s, plan, uid: plan is not None
    ),
    ToolSpec(
        GET_PLAN_TOOL, SessionService._handle_get_plan, lambda s, plan, uid: plan is not None
    ),
    ToolSpec(
        PRACTICE_RECORD_TOOL,
        SessionService._handle_practice_record,
        lambda s, plan, uid: s._revision_service is not None and bool(uid),
    ),
    ToolSpec(
        FIND_PROBLEMS_TOOL,
        SessionService._handle_find_problems,
        lambda s, plan, uid: (
            s._library_service is not None and s._problem_session_service is not None and bool(uid)
        ),
    ),
    ToolSpec(
        SET_PROBLEM_FLAG_TOOL,
        SessionService._handle_set_problem_flag,
        lambda s, plan, uid: (
            s._library_service is not None and s._problem_session_service is not None and bool(uid)
        ),
    ),
    ToolSpec(
        CREATE_PRACTICE_PLAN_TOOL,
        SessionService._handle_create_practice_plan,
        lambda s, plan, uid: (
            s._library_service is not None and s._curriculum_service is not None and bool(uid)
        ),
    ),
)


def _spec_for(name: str) -> ToolSpec | None:
    return next((spec for spec in TOOLS if spec.tool.name == name), None)
