import logging
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator

from app.curriculum.application.services import CurriculumService
from app.llm.domain.provider import LLMProvider
from app.llm.domain.requests import ChatStreamRequest, ChatTurn
from app.llm.prompts.chat import (
    CREATE_PRACTICE_PLAN_TOOL,
    EDIT_PLAN_TOOL,
    FIND_PROBLEMS_TOOL,
    GENERATE_PLAN_TOOL,
    PRACTICE_RECORD_TOOL,
    SET_PROBLEM_FLAG_TOOL,
    SUPPORTED_LANGUAGES,
    chat_system_prompt,
    library_context,
    library_memo,
    mastery_context,
)
from app.revision.application.services import RevisionService
from app.curriculum.domain.models import LessonNodeStatus
from app.sessions.domain.models import ChatMessage, ChatRole, LearningSession, SessionStatus
from app.sessions.domain.repository import SessionRepository
from app.shared.errors import NotFoundError
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
        now = datetime.now(timezone.utc)
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
        {"type": "tool_start", "label": ...} when a plan-generation tool call begins
        (persisted as a real ChatRole.SYSTEM message, not just a UI-only event),
        {"type": "done", "message_id", "content"} once the final assistant reply lands."""
        existing = await self._repository.get(session_id)
        # A reply's `intent` carries what its tool returned — the ids, above all. Without it
        # the model reaches a follow-up "yes" holding titles and nothing to act on, so it
        # re-searches or guesses; that single gap is what made "yes" loop.
        history = [
            ChatTurn(
                role="user" if m.role == ChatRole.USER else "assistant",
                content=(
                    f"{m.content}\n\n[tool context — yours to act on, never repeat to the "
                    f"user]\n{m.intent}"
                    if m.intent
                    else m.content
                ),
            )
            for m in (existing.messages if existing else [])
            if m.role in (ChatRole.USER, ChatRole.ASSISTANT)
        ][-MAX_HISTORY_TURNS:]

        user_message = ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=ChatRole.USER,
            content=content,
            created_at=datetime.now(timezone.utc),
        )
        await self._repository.add_message(user_message)
        yield {"type": "user_message", "message_id": user_message.id}

        if self._llm_provider is None:
            return

        existing_plan = False
        if self._curriculum_service is not None:
            try:
                existing_plan = bool(await self._curriculum_service.list_for_session(session_id))
            except Exception:
                logger.warning("Failed to check for an existing plan for session %s", session_id, exc_info=True)

        # Deliberately NOT caught here: app/shared/sse.py logs it and emits a terminal
        # error frame. Swallowing it used to close the stream cleanly with no reply, which
        # the client could not distinguish from the assistant choosing to say nothing.
        user_id = existing.user_id if existing is not None else None
        async for event in self._stream_reply(session_id, history, content, existing_plan, user_id):
            yield event

    async def _stream_reply(
        self,
        session_id: str,
        history: list[ChatTurn],
        message: str,
        existing_plan: bool,
        user_id: str | None,
        depth: int = 0,
    ) -> AsyncIterator[dict]:
        request = ChatStreamRequest(
            system_prompt=chat_system_prompt(existing_plan, (await get_preferences())["default_language"]),
            history=history,
            message=message,
            tools=self._tools_for(existing_plan, user_id),
        )
        text_parts: list[str] = []
        async for chunk in self._llm_provider.stream_chat(request):
            if chunk.text_delta:
                text_parts.append(chunk.text_delta)
                yield {"type": "text_delta", "delta": chunk.text_delta}
            if chunk.tool_call is not None:
                handler = self._handler_for(
                    chunk.tool_call, session_id, history, message, existing_plan, user_id, depth
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

    def _tools_for(self, existing_plan: bool, user_id: str | None) -> list:
        # edit_learning_plan is only offered once a plan exists — there's nothing to edit
        # otherwise, and omitting it keeps the model from reaching for it prematurely.
        return (
            [GENERATE_PLAN_TOOL]
            + ([EDIT_PLAN_TOOL] if existing_plan else [])
            # Only offered when there's a record to look up. Fetching it on every turn would
            # be a wasted query on the many turns that never mention progress.
            + ([PRACTICE_RECORD_TOOL] if self._revision_service is not None and user_id else [])
            # The problem bank. Without these the model can only ever make something new —
            # it cannot see or name a problem the learner already has.
            + (
                [FIND_PROBLEMS_TOOL, SET_PROBLEM_FLAG_TOOL]
                if self._library_service is not None
                and self._problem_session_service is not None
                and user_id
                else []
            )
            + (
                [CREATE_PRACTICE_PLAN_TOOL]
                if self._library_service is not None and self._curriculum_service is not None and user_id
                else []
            )
        )

    def _handler_for(
        self,
        tool_call,
        session_id: str,
        history: list[ChatTurn],
        message: str,
        existing_plan: bool,
        user_id: str | None,
        depth: int,
    ) -> AsyncIterator[dict] | None:
        """Routes one tool call to its handler, or None when the name matches nothing.

        Shared by the first call of a turn and by any chained call after it, so a follow-up
        tool call behaves exactly like an opening one — that symmetry is the point."""
        args = tool_call.args
        if tool_call.name == "generate_learning_plan":
            return self._handle_generate_plan(
                session_id, args, history, message, existing_plan, user_id, depth
            )
        if tool_call.name == "edit_learning_plan":
            return self._handle_edit_plan(session_id, args, history, message, depth)
        if tool_call.name == "get_practice_record":
            return self._handle_practice_record(
                session_id, user_id, history, message, existing_plan, depth
            )
        if tool_call.name == "find_problems":
            return self._handle_find_problems(
                session_id, args, history, message, existing_plan, user_id, depth
            )
        if tool_call.name == "create_practice_plan":
            return self._handle_create_practice_plan(
                session_id, args, history, message, existing_plan, depth
            )
        if tool_call.name == "set_problem_flag":
            return self._handle_set_problem_flag(
                session_id, args, history, message, existing_plan, user_id, depth
            )
        return None

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

    async def _handle_generate_plan(
        self,
        session_id: str,
        args: dict,
        history: list[ChatTurn],
        user_message: str,
        existing_plan: bool,
        user_id: str | None,
        depth: int = 0,
    ) -> AsyncIterator[dict]:
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
                session_id, history, user_message, existing_plan,
                "generate_learning_plan", summary, fallback, None,
                depth=depth,
            ):
                yield event
            return

        label = "Updating your learning plan..." if existing_plan else "Generating a learning plan..."
        system_note = ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=ChatRole.SYSTEM,
            content=label,
            created_at=datetime.now(timezone.utc),
        )
        await self._repository.add_message(system_note)
        yield {"type": "tool_start", "label": label, "message_id": system_note.id}

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
            result_summary = (
                f"Generated a learning plan for '{plan.topic}' with {len(plan.nodes)} steps."
            )
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
            existing_plan,
            "generate_learning_plan",
            result_summary,
            fallback,
            plan.id if plan is not None else None,
            depth=depth,
        ):
            yield event

    @staticmethod
    def _plan_step_summary(plan) -> str:
        steps = ", ".join(f"{n.sequence_index + 1}. {n.skill_name or n.skill_id}" for n in plan.nodes)
        return f"It now has {len(plan.nodes)} steps: {steps}."

    async def _handle_edit_plan(
        self,
        session_id: str,
        args: dict,
        history: list[ChatTurn],
        user_message: str,
        depth: int = 0,
    ) -> AsyncIterator[dict]:
        """Single entry point for every kind of plan edit — the operation named in `args`
        picks a deterministic, targeted CurriculumService method (no LLM call, no other
        step touched) for everything except "rework", the only operation that still calls
        revise_curriculum for a genuinely broad, unstructured change."""
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
            async for event in self._stream_tool_followup(
                session_id, history, user_message, True, "edit_learning_plan",
                "NOT RUN — there is no plan for this session to edit. Tell the user "
                "something went wrong and they can try again.",
                "I couldn't find a plan to edit — want to try again?",
                None,
                depth=depth,
            ):
                yield event
            return

        if operation == "change_language":
            requested_language = (args.get("language") or "").strip().lower()
            try:
                language = Language(requested_language)
            except ValueError:
                supported = ", ".join(SUPPORTED_LANGUAGES)
                async for event in self._stream_tool_followup(
                    session_id, history, user_message, True, "edit_learning_plan",
                    f"NOT RUN — '{requested_language or 'no language'}' is not a supported "
                    f"language. Nothing was changed. Tell the user the supported languages "
                    f"are {supported} and ask them to pick one.",
                    f"I can do {supported} — which would you like?",
                    None,
                    depth=depth,
                ):
                    yield event
                return
            label = f"Switching the plan to {language.value}..."
            action = lambda: self._curriculum_service.set_plan_language(plan_id, language)
            done_text = lambda plan: (
                f"Switched the plan to {plan.language.value}. Steps and completed progress "
                "are unchanged; new problems will generate in the new language."
            )
        elif operation == "change_step_difficulty":
            step = str(args.get("step") or "").strip()
            difficulty = (args.get("difficulty") or "").strip().lower()
            if not step or difficulty not in {"easy", "medium", "hard"}:
                async for event in self._stream_tool_followup(
                    session_id, history, user_message, True, "edit_learning_plan",
                    "NOT RUN — missing which step or what difficulty to set. Ask the user "
                    "which step and how much harder/easier.",
                    "Which step, and how much harder or easier?", None,
                    depth=depth,
                ):
                    yield event
                return
            label = f"Adjusting step {step}..."
            action = lambda: self._curriculum_service.set_step_difficulty(plan_id, step, difficulty)
            done_text = lambda plan: f"Updated that step's difficulty. {self._plan_step_summary(plan)}"
        elif operation == "add_step":
            skill = str(args.get("skill") or "").strip()
            if not skill:
                async for event in self._stream_tool_followup(
                    session_id, history, user_message, True, "edit_learning_plan",
                    "NOT RUN — no skill/topic given for the new step. Ask the user what it "
                    "should cover.",
                    "What should the new step cover?", None,
                    depth=depth,
                ):
                    yield event
                return
            difficulty = args.get("difficulty") or None
            position = args.get("position")
            label = f"Adding a step on {skill}..."
            action = lambda: self._curriculum_service.add_step(plan_id, skill, difficulty, position)
            done_text = lambda plan: f"Added the new step. {self._plan_step_summary(plan)}"
        elif operation == "add_problem":
            problem_id = str(args.get("problem_id") or "").strip()
            if not problem_id:
                async for event in self._stream_tool_followup(
                    session_id, history, user_message, True, "edit_learning_plan",
                    "NOT RUN — no problem id given. Call find_problems to get one, then try "
                    "again. Do not invent an id.",
                    "Which problem did you want me to add?", None,
                    depth=depth,
                ):
                    yield event
                return
            label = "Adding that problem to your plan..."
            action = lambda: self._curriculum_service.add_problem_step(plan_id, problem_id)
            done_text = lambda plan: (
                "Added it to their plan as a new step — it opens that exact problem, nothing "
                f"regenerated. Tell them it's on their plan and ready to start. "
                f"{self._plan_step_summary(plan)}"
            )
        elif operation == "remove_step":
            step = str(args.get("step") or "").strip()
            if not step:
                async for event in self._stream_tool_followup(
                    session_id, history, user_message, True, "edit_learning_plan",
                    "NOT RUN — no step named to remove. Ask the user which one.",
                    "Which step should I remove?", None,
                    depth=depth,
                ):
                    yield event
                return
            label = f"Removing step {step}..."
            action = lambda: self._curriculum_service.remove_step(plan_id, step)
            done_text = lambda plan: f"Removed that step. {self._plan_step_summary(plan)}"
        elif operation == "reorder_step":
            step = str(args.get("step") or "").strip()
            to_position = args.get("to_position")
            if not step or to_position is None:
                async for event in self._stream_tool_followup(
                    session_id, history, user_message, True, "edit_learning_plan",
                    "NOT RUN — missing which step or where to move it. Ask the user for both.",
                    "Which step, and where should it move to?", None,
                    depth=depth,
                ):
                    yield event
                return
            label = f"Reordering step {step}..."
            action = lambda: self._curriculum_service.reorder_step(plan_id, step, to_position)
            done_text = lambda plan: f"Reordered the plan. {self._plan_step_summary(plan)}"
        else:
            instruction = args.get("instruction") or user_message
            label = "Updating your learning plan..."
            action = lambda: self._curriculum_service.edit_plan(plan_id, instruction)
            done_text = lambda plan: f"Updated the plan. {self._plan_step_summary(plan)}"

        system_note = ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=ChatRole.SYSTEM,
            content=label,
            created_at=datetime.now(timezone.utc),
        )
        await self._repository.add_message(system_note)
        yield {"type": "tool_start", "label": label, "message_id": system_note.id}

        plan = None
        not_found: NotFoundError | None = None
        try:
            plan = await action()
        except NotFoundError as exc:
            not_found = exc
        except Exception:
            logger.warning("Plan edit (%s) failed for session %s", operation, session_id, exc_info=True)

        if plan is not None:
            result_summary = done_text(plan)
            fallback = "Updated your plan — open it with the corner button to see the changes."
        elif not_found is not None:
            result_summary = (
                f"NOT RUN — {not_found}. Nothing was changed. Tell the user this plainly and "
                "ask them to clarify or try something else."
            )
            fallback = f"{not_found} — want to try something else?"
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
        ):
            yield event

    async def _handle_practice_record(
        self,
        session_id: str,
        user_id: str | None,
        history: list[ChatTurn],
        user_message: str,
        existing_plan: bool,
        depth: int = 0,
    ) -> AsyncIterator[dict]:
        """Read-only lookup — nothing is persisted and no tool_start note is shown, because
        from the user's side this is the assistant answering, not doing."""
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
            existing_plan,
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

    async def _handle_find_problems(
        self,
        session_id: str,
        args: dict,
        history: list[ChatTurn],
        user_message: str,
        existing_plan: bool,
        user_id: str | None,
        depth: int = 0,
    ) -> AsyncIterator[dict]:
        """Read-only lookup over the learner's own problems — same shape as
        _handle_practice_record: nothing persisted, no tool_start note, because from their
        side this is the assistant answering rather than doing."""
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
            existing_plan,
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
            # THE fix for a follow-up "yes": the prose above is told to keep ids quiet, so
            # without this the next turn has titles and nothing to act on.
            memo=library_memo(entries),
            depth=depth,
        ):
            yield event

    async def _handle_create_practice_plan(
        self,
        session_id: str,
        args: dict,
        history: list[ChatTurn],
        user_message: str,
        existing_plan: bool,
        depth: int = 0,
    ) -> AsyncIterator[dict]:
        """A plan whose steps are problems the learner already has. Costs no LLM call and
        no sandbox run — every step reopens its bound problem directly."""
        problem_ids = [str(value) for value in (args.get("problem_ids") or []) if value]
        topic = (args.get("topic") or "Revision").strip() or "Revision"

        if not problem_ids:
            async for event in self._stream_tool_followup(
                session_id, history, user_message, existing_plan,
                "create_practice_plan",
                "NOT RUN — no problems were given, so no plan was built. Ask which "
                "problems they want in it.",
                "Which problems should I put in it?",
                None,
                depth=depth,
            ):
                yield event
            return

        label = f"Building a plan from {len(problem_ids)} problem(s)..."
        system_note = ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=ChatRole.SYSTEM,
            content=label,
            created_at=datetime.now(timezone.utc),
        )
        await self._repository.add_message(system_note)
        yield {"type": "tool_start", "label": label, "message_id": system_note.id}

        plan = None
        try:
            plan = await self._curriculum_service.create_practice_plan(
                session_id, problem_ids, topic
            )
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
                "Each step reopens that exact problem. " + self._plan_step_summary(plan)
            )
            fallback = f"Built you a {len(plan.nodes)}-step plan from those problems."

        async for event in self._stream_tool_followup(
            session_id,
            history,
            user_message,
            existing_plan,
            "create_practice_plan",
            summary,
            fallback,
            plan.id if plan is not None else None,
            depth=depth,
        ):
            yield event

    async def _handle_set_problem_flag(
        self,
        session_id: str,
        args: dict,
        history: list[ChatTurn],
        user_message: str,
        existing_plan: bool,
        user_id: str | None,
        depth: int = 0,
    ) -> AsyncIterator[dict]:
        problem_id = (args.get("problem_id") or "").strip()
        flagged = bool(args.get("flagged"))
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
        summary = (
            f"{verb} that problem."
            if ok
            else "NOT RUN — the flag could not be changed. Tell the user plainly."
        )
        async for event in self._stream_tool_followup(
            session_id, history, user_message, existing_plan,
            "set_problem_flag", summary,
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
        existing_plan: bool,
        tool_name: str,
        result_summary: str,
        fallback_text: str,
        plan_id: str | None,
        instruction: str = (
            "Reply to the user in one or two plain sentences telling them what changed."
        ),
        memo: str | None = None,
        depth: int = 0,
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
        chain_user_id, chain_plan = None, existing_plan
        if may_chain:
            session = await self._repository.get(session_id)
            chain_user_id = session.user_id if session is not None else None
            # A tool may have just created the plan the next one needs to edit.
            if not chain_plan and self._curriculum_service is not None:
                try:
                    chain_plan = bool(
                        await self._curriculum_service.list_for_session(session_id)
                    )
                except Exception:
                    logger.warning("Plan re-check failed for %s", session_id, exc_info=True)

        follow_up_request = ChatStreamRequest(
            system_prompt=chat_system_prompt(existing_plan, (await get_preferences())["default_language"]),
            history=history + [ChatTurn(role="user", content=user_message)],
            message=(
                f"[{tool_name} tool result] {result_summary}\n\n"
                f"The tool has ALREADY run and this is its result. {instruction} "
                + (
                    "If the user asked for something this result has not finished — another "
                    "step of the same request — call the tool that finishes it now. "
                    "Otherwise reply in prose and call nothing."
                    if may_chain
                    else "Do not call any tool, and never output JSON, a function call, or "
                    "code — only prose."
                )
            ),
            tools=self._tools_for(chain_plan, chain_user_id) if may_chain else [],
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
                    chunk.tool_call, session_id, history, chained_context,
                    chain_plan, chain_user_id, depth + 1,
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
            created_at=datetime.now(timezone.utc),
        )
        await self._repository.add_message(reply)
        return reply
