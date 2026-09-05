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
    library_context,
    library_memo,
    mastery_context,
    plan_context,
)
from app.revision.application.services import RevisionService
from app.sessions.application import plan_edits
from app.sessions.application.tool_registry import ToolContext, ToolSpec
from app.sessions.domain.models import ChatMessage, ChatRole, LearningSession, SessionStatus
from app.sessions.domain.repository import SessionRepository
from app.shared.errors import AgentError, ConflictError, NotFoundError
from app.shared.preferences import get_preferences
from app.shared.types import Language

logger = logging.getLogger(__name__)

# Every turn resends the whole history, so an uncapped transcript makes cost grow
# quadratically over a session and eventually just fails on the context limit. The tail is
# what the model actually needs — this is a chat about what to learn next, not a document.
MAX_HISTORY_TURNS = 20

# Tool calls one user message may trigger. Two covers the real compound asks — look
# something up then act on it, clear the plan then add to it — while still guaranteeing the
# turn ends in prose rather than looping tools at the model's discretion.
MAX_TOOL_CHAIN = 2


class SessionService:
    """Session/chat persistence. Chat is not the memory system — but a
    user message now gets a real, streamed assistant reply: the model itself decides,
    from conversation context, when to call the generate_learning_plan tool (no manual
    button, no static templated reply) — see add_message/_stream_reply."""

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
        # Lets the agent see the problems this learner already has, instead of only skills.
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
        """Persists the user's message, then streams the assistant's reply as a sequence
        of event dicts a router can turn straight into SSE frames:
        {"type": "user_message", ...} once the user's own message is saved,
        {"type": "text_delta", "delta": ...} for each streamed token,
        {"type": "tool_start", "label": ...} when a tool call begins. Tools that change
        something also carry a message_id, because their label is persisted as a
        ChatRole.SYSTEM message; a lookup's label is transient and carries none,
        {"type": "done", "message_id", "content"} once the final assistant reply lands."""
        existing = await self._repository.get(session_id)
        # A reply's `intent` carries what its tool returned — the ids, above all. Without it
        # the model reaches a follow-up "yes" holding titles and nothing to act on, so it
        # re-searches or guesses; that single gap is what made "yes" loop.
        conversation = [
            m
            for m in (existing.messages if existing else [])
            if m.role in (ChatRole.USER, ChatRole.ASSISTANT)
        ][-MAX_HISTORY_TURNS:]
        # Only the LAST memo is still live — it exists so a follow-up "yes" has the ids of
        # what was just offered. Older ones describe offers already answered, and at ~1KB
        # of stale ids each they were re-sent on every turn for the rest of the window.
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

        # The plan itself, not a bool: get_learning_plan answers out of it, so the lookup
        # this turn already ran is the whole cost. list_for_session is newest-first.
        active_plan = None
        if self._curriculum_service is not None:
            try:
                plans = await self._curriculum_service.list_for_session(session_id)
                active_plan = plans[0] if plans else None
            except Exception:
                logger.warning(
                    "Failed to check for an existing plan for session %s", session_id, exc_info=True
                )

        # Not caught here: app/shared/sse.py logs it and emits a terminal
        # error frame. Swallowing it used to close the stream cleanly with no reply, which
        # the client could not distinguish from the assistant choosing to say nothing.
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

        # A blank completion (safety stop, or a tool call that matched no handler) would
        # otherwise end the stream with no assistant turn at all — same blank screen as a
        # crash. Persist a real reply so the transcript stays a conversation.
        reply_text = "".join(text_parts).strip() or (
            "I didn't manage to put together a reply there. Could you rephrase that?"
        )
        reply = await self._persist_assistant_reply(session_id, reply_text)
        yield {"type": "done", "message_id": reply.id, "content": reply_text}

    async def _system_prompt(self, active_plan: LessonPlan | None, user_id: str | None) -> str:
        """The same conditions _tools_for gates the tools on, so the prompt never explains
        a tool this session was not given."""
        return chat_system_prompt(
            active_plan,
            (await get_preferences())["default_language"],
            has_record=self._revision_service is not None and bool(user_id),
            has_library=self._library_service is not None and bool(user_id),
        )

    def _tools_for(self, active_plan: LessonPlan | None, user_id: str | None) -> list:
        """What the model may call this turn.

        The list is deliberately the SAME on a follow-up call as on the opening one. Dropping
        the lookup tools afterwards saved ~500 tokens of schema, but the tool declarations sit
        in the request prefix next to the system prompt, and changing the prefix forfeits
        Gemini's cached-token discount on the whole ~4.2k of it — several times what it saved.
        The prompt already tells the model not to re-run a lookup, and MAX_TOOL_CHAIN caps it
        regardless."""
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
        """Routes one tool call to its handler, or None when the name matches nothing.

        Shared by the first call of a turn and by any chained call after it, so a follow-up
        tool call behaves exactly like an opening one — that symmetry is the point."""
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
        """The one place a tool writes its status line. A chained tool is handed the note id
        the previous one made and rewrites that line instead of stacking a second, so a
        two-tool turn ("a new one in python") reads as one step — the same single line a
        lookup-then-act chain already gets by persisting nothing on the lookup."""
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
        """Explicit user language always wins. Absent that, the configured default fills in
        — unless it's "ask" (or unset), which behaves exactly as if nothing were configured
        and a clarifying question is needed."""
        if requested_language:
            try:
                return Language(requested_language)
            except ValueError:
                return None
        default = (await get_preferences())["default_language"]
        return Language(default) if default != "ask" else None

    async def _handle_generate_plan(self, call: ToolContext) -> AsyncIterator[dict]:
        session_id, args, history, user_message, active_plan, user_id, depth, note_id = (
            call.session_id,
            call.args,
            call.history,
            call.message,
            call.active_plan,
            call.user_id,
            call.depth,
            call.note_id,
        )
        # Enforced here, not just in the prompt: a plan in a language the learner never
        # chose — or one the sandbox cannot run — is worse than no plan, and
        # asking-while-also-building reads as a contradiction. Nothing is persisted and no
        # "Generating..." note is shown.
        requested_language = (args.get("language") or "").strip().lower()
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
                fallback = f"Which language would you like to practise in? I support {supported}."
            async for event in self._stream_tool_followup(
                session_id,
                history,
                user_message,
                active_plan,
                "generate_learning_plan",
                summary,
                fallback,
                None,
                depth=depth,
            ):
                yield event
            return

        label = "Updating your learning plan..." if active_plan else "Generating a learning plan..."
        event = await self._announce(session_id, label, note_id)
        note_id = event["message_id"]
        yield event

        topic = args.get("topic") or "this topic"
        level = args.get("level") or "beginner"
        step_count = args.get("step_count")
        target_problem = args.get("target_problem") or None

        plan = None
        if self._curriculum_service is not None:
            try:
                plan = await self._curriculum_service.create_draft(
                    session_id,
                    topic,
                    language,
                    level,
                    step_count=int(step_count) if step_count else None,
                    target_problem=target_problem,
                    user_id=user_id,
                )
            except Exception:
                logger.warning("Plan generation failed for session %s", session_id, exc_info=True)

        if plan is not None:
            # Steps that start DONE were skipped because the learner has already proven the
            # skill. Saying so matters: a plan that opens half-complete looks like a bug.
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
        async for event in self._stream_tool_followup(
            session_id,
            history,
            user_message,
            active_plan,
            "generate_learning_plan",
            result_summary,
            fallback,
            plan.id if plan is not None else None,
            depth=depth,
            note_id=note_id,
        ):
            yield event

    def _refuse(self, session_id, history, user_message, tool_name, summary, fallback, depth):
        """A tool call that never ran, and why. The summary is what the model reads."""
        return self._stream_tool_followup(
            session_id,
            history,
            user_message,
            True,
            tool_name,
            summary,
            fallback,
            None,
            depth=depth,
        )

    async def _handle_edit_plan(self, call: ToolContext) -> AsyncIterator[dict]:
        """Single entry point for every kind of plan edit — the operation named in `args`
        picks a deterministic, targeted CurriculumService method (no LLM call, no other
        step touched) for everything except "rework", the only operation that still calls
        revise_curriculum for a genuinely broad, unstructured change."""
        session_id, args, history, user_message, depth, note_id = (
            call.session_id,
            call.args,
            call.history,
            call.message,
            call.depth,
            call.note_id,
        )
        operation = args.get("operation") or "rework"

        plan_id = None
        if self._curriculum_service is not None:
            try:
                # list_for_session is newest-first, so [0] is the session's active plan.
                plans = await self._curriculum_service.list_for_session(session_id)
                plan_id = plans[0].id if plans else None
            except Exception:
                logger.warning("Failed to look up the active plan for session %s", session_id, exc_info=True)

        if plan_id is None:
            async for event in self._refuse(
                session_id,
                history,
                user_message,
                "edit_learning_plan",
                "NOT RUN — there is no plan for this session to edit. Tell the user "
                "something went wrong and they can try again.",
                "I couldn't find a plan to edit — want to try again?",
                depth,
            ):
                yield event
            return

        outcome = plan_edits.build(operation, args, plan_id, self._curriculum_service, user_message)
        if isinstance(outcome, plan_edits.Refusal):
            async for event in self._refuse(
                session_id,
                history,
                user_message,
                "edit_learning_plan",
                outcome.summary,
                outcome.fallback,
                depth,
            ):
                yield event
            return
        label, action, done_text = outcome.label, outcome.action, outcome.done_text

        event = await self._announce(session_id, label, note_id)
        note_id = event["message_id"]
        yield event

        plan = None
        not_run: AgentError | None = None
        try:
            plan = await action()
        except (NotFoundError, ConflictError) as exc:
            not_run = exc
        except Exception:
            logger.warning("Plan edit (%s) failed for session %s", operation, session_id, exc_info=True)

        if plan is not None:
            result_summary = done_text(plan)
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

        async for event in self._stream_tool_followup(
            session_id,
            history,
            user_message,
            True,
            "edit_learning_plan",
            result_summary,
            fallback,
            plan.id if plan is not None else None,
            depth=depth,
            note_id=note_id,
        ):
            yield event

    async def _handle_get_plan(self, call: ToolContext) -> AsyncIterator[dict]:
        """Read-only lookup, same transient shape as _handle_practice_record.

        The plan is already loaded for this turn, so answering costs no query — it is only
        gated behind a tool call so a dozen lines of steps stay out of the prompt on the
        turns that never ask about them."""
        yield {"type": "tool_start", "label": "Reading your plan..."}

        async for event in self._stream_tool_followup(
            call.session_id,
            call.history,
            call.message,
            call.active_plan,
            "get_learning_plan",
            plan_context(call.active_plan),
            "I couldn't read your plan just then — want me to try again?",
            None,
            instruction=(
                "Answer their question from this plan and nothing else. Use the step "
                "numbers and names exactly as given, and never describe a step that is not "
                "on the list."
            ),
            # Carried so a follow-up ('and step 6?') needs no second call.
            memo=plan_context(call.active_plan),
            depth=call.depth,
        ):
            yield event

    async def _handle_practice_record(self, call: ToolContext) -> AsyncIterator[dict]:
        """Read-only lookup. The label is transient — unlike the tools that change
        something, nothing is persisted, so it leaves no line in the transcript."""
        session_id, user_id, history, user_message, active_plan, depth = (
            call.session_id,
            call.user_id,
            call.history,
            call.message,
            call.active_plan,
            call.depth,
        )
        yield {"type": "tool_start", "label": "Checking your progress..."}

        candidates = []
        if self._revision_service is not None and user_id:
            try:
                candidates = await self._revision_service.get_revision_queue(user_id)
            except Exception:
                logger.warning("Failed to load the practice record for %s", user_id, exc_info=True)

        # How much work they've actually done. Same question the model calls this tool for,
        # so it rides along rather than costing a second round trip.
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

        async for event in self._stream_tool_followup(
            session_id,
            history,
            user_message,
            active_plan,
            "get_practice_record",
            record,
            (
                "Here's where you're at — want me to build a plan around one of these?"
                if candidates
                else "You haven't finished any practice problems yet, so I've nothing to go on. "
                "What would you like to work on?"
            ),
            None,
            instruction=(
                "Answer their question from it: name the two or three topics worth their time, "
                "a few words on why each, then ask if they want a plan for one. Use the skill "
                "names exactly as given and do not invent any. Do not read the scores out as "
                "numbers."
            ),
            depth=depth,
        ):
            yield event

    async def _handle_find_problems(self, call: ToolContext) -> AsyncIterator[dict]:
        """Read-only lookup over the learner's own problems. Transient label, nothing
        persisted — same shape as _handle_practice_record."""
        session_id, args, history, user_message, active_plan, user_id, depth = (
            call.session_id,
            call.args,
            call.history,
            call.message,
            call.active_plan,
            call.user_id,
            call.depth,
        )
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

        async for event in self._stream_tool_followup(
            session_id,
            history,
            user_message,
            active_plan,
            "find_problems",
            library_context(entries, scope, stats),
            (
                "Here's what I found — want me to put one on your plan?"
                if entries
                else "I couldn't find anything matching that. Want me to make you a new one?"
            ),
            None,
            instruction=(
                "Answer their question from this list. Name problems by TITLE and never "
                "read an id out loud. Do not mention any problem that is not on the list, "
                "and do not invent one. If they want to work on one, offer to add it to "
                "their plan — this chat builds plans, it does not open problems."
            ),
            # Needed for a follow-up "yes": the prose above keeps ids quiet, so
            # without this the next turn has titles and nothing to act on.
            memo=library_memo(entries),
            depth=depth,
        ):
            yield event

    async def _handle_create_practice_plan(self, call: ToolContext) -> AsyncIterator[dict]:
        """A plan whose steps are problems the learner already has. Costs no LLM call and
        no sandbox run — every step reopens its bound problem directly."""
        session_id, args, history, user_message, active_plan, depth, note_id = (
            call.session_id,
            call.args,
            call.history,
            call.message,
            call.active_plan,
            call.depth,
            call.note_id,
        )
        problem_ids = [str(value) for value in (args.get("problem_ids") or []) if value]
        topic = (args.get("topic") or "Revision").strip() or "Revision"

        if not problem_ids:
            async for event in self._stream_tool_followup(
                session_id,
                history,
                user_message,
                active_plan,
                "create_practice_plan",
                "NOT RUN — no problems were given, so no plan was built. Ask which problems they want in it.",
                "Which problems should I put in it?",
                None,
                depth=depth,
            ):
                yield event
            return

        label = f"Building a plan from {len(problem_ids)} problem(s)..."
        event = await self._announce(session_id, label, note_id)
        note_id = event["message_id"]
        yield event

        plan = None
        try:
            plan = await self._curriculum_service.create_practice_plan(session_id, problem_ids, topic)
        except NotFoundError as exc:
            summary = f"NOT RUN — {exc} Tell the user and offer to find the problems again."
            fallback = "I couldn't build that plan — want me to look up those problems again?"
        except Exception:
            logger.warning("Practice plan failed for session %s", session_id, exc_info=True)
            summary = "Plan build failed — tell the user something went wrong."
            fallback = "Something went wrong building that plan — want me to try again?"

        if plan is not None:
            summary = (
                f"Built a {len(plan.nodes)}-step plan out of problems they already have. "
                "Each step reopens that exact problem. " + plan_edits.plan_step_summary(plan)
            )
            fallback = f"Built you a {len(plan.nodes)}-step plan from those problems."

        async for event in self._stream_tool_followup(
            session_id,
            history,
            user_message,
            active_plan,
            "create_practice_plan",
            summary,
            fallback,
            plan.id if plan is not None else None,
            depth=depth,
            note_id=note_id,
        ):
            yield event

    async def _handle_set_problem_flag(self, call: ToolContext) -> AsyncIterator[dict]:
        session_id, args, history, user_message, active_plan, user_id, depth = (
            call.session_id,
            call.args,
            call.history,
            call.message,
            call.active_plan,
            call.user_id,
            call.depth,
        )
        problem_id = (args.get("problem_id") or "").strip()
        flagged = bool(args.get("flagged"))
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
        async for event in self._stream_tool_followup(
            session_id,
            history,
            user_message,
            active_plan,
            "set_problem_flag",
            summary,
            f"{verb} it for you." if ok else "I couldn't change that flag — want me to try again?",
            None,
            depth=depth,
        ):
            yield event

    async def _stream_tool_followup(
        self,
        session_id: str,
        history: list[ChatTurn],
        user_message: str,
        active_plan: LessonPlan | None,
        tool_name: str,
        result_summary: str,
        fallback_text: str,
        plan_id: str | None,
        instruction: str = ("Reply to the user in one or two plain sentences telling them what changed."),
        memo: str | None = None,
        depth: int = 0,
        note_id: str | None = None,
    ) -> AsyncIterator[dict]:
        """Feeds a tool's result back to the model for a natural closing line, streamed like
        any other reply, then persists it. Shared by every tool.

        memo rides along on the persisted reply so the NEXT turn still has what this tool
        returned — the ids especially, which the closing prose is told to keep quiet about.

        One request often needs two tools ("remove everything and add that one"; a lookup
        followed by acting on what it found). Below MAX_TOOL_CHAIN the model may therefore
        call another tool here rather than only speak — without that it emits a tool call
        the guard has to blank, and the user gets a canned fallback instead of the thing
        they asked for."""
        may_chain = depth + 1 < MAX_TOOL_CHAIN
        chained_context = f"{user_message}\n\n[{tool_name} tool result]\n{result_summary}"
        # Resolved even when we cannot chain: it decides which coaching blocks the system
        # prompt carries, and letting it fall to None on the last call of a turn would
        # quietly hand that call a different prompt than the rest of the turn.
        session = await self._repository.get(session_id)
        chain_user_id = session.user_id if session is not None else None
        chain_plan = active_plan
        if may_chain and self._curriculum_service is not None:
            # Unconditional, not just when there was no plan: the tool that just ran may have
            # created the plan the next one edits, or edited the one a chained
            # get_learning_plan is about to read back. Either way the copy from the top of
            # the turn is stale.
            try:
                plans = await self._curriculum_service.list_for_session(session_id)
                chain_plan = plans[0] if plans else None
            except Exception:
                logger.warning("Plan re-check failed for %s", session_id, exc_info=True)

        follow_up_request = ChatStreamRequest(
            # chain_plan, not active_plan: a tool may have just created the plan, and
            # calling it absent while offering edit_learning_plan alongside is both wrong
            # and a needless second variant of an otherwise identical, cacheable prompt.
            system_prompt=await self._system_prompt(chain_plan, chain_user_id),
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
            tools=(self._tools_for(chain_plan, chain_user_id) if may_chain else []),
        )
        # The model sometimes answers a tool result by echoing another tool call as raw
        # JSON. Nothing is streamed until the text is known not to be one, so a blob can
        # never reach the UI — we fall back to plain prose instead.
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
                    chain_user_id,
                    depth + 1,
                    note_id,
                )
                if chained is not None:
                    # ponytail: this call's memo is dropped — the chained handler persists
                    # the only reply, and threading a memo through every handler to save it
                    # isn't worth it. A chain has already DONE the thing, so there is no
                    # pending offer whose ids the next turn needs.
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


# Defined after the class because it names its methods. Everything about a tool — when it is
# offered, whether it survives a lookup, and what runs it — is here and nowhere else.
TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(GENERATE_PLAN_TOOL, SessionService._handle_generate_plan, lambda s, plan, uid: True),
    # Nothing to edit before a plan exists, and offering it stops the model reaching for it.
    ToolSpec(
        EDIT_PLAN_TOOL, SessionService._handle_edit_plan, lambda s, plan, uid: plan is not None
    ),
    # Same gate: with no plan there is nothing to read, and the model asked to describe one
    # anyway reaches for whatever list is nearest.
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
