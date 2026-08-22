import logging
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator

from app.curriculum.application.services import CurriculumService
from app.llm.domain.provider import LLMProvider
from app.llm.domain.requests import ChatStreamRequest, ChatTurn
from app.llm.prompts.chat import (
    EDIT_PLAN_TOOL,
    GENERATE_PLAN_TOOL,
    PRACTICE_RECORD_TOOL,
    SUPPORTED_LANGUAGES,
    chat_system_prompt,
    mastery_context,
)
from app.revision.application.services import RevisionService
from app.sessions.domain.models import ChatMessage, ChatRole, LearningSession, SessionStatus
from app.sessions.domain.repository import SessionRepository
from app.shared.types import Language

logger = logging.getLogger(__name__)

# Every turn resends the whole history, so an uncapped transcript makes cost grow
# quadratically over a session and eventually just fails on the context limit. The tail is
# what the model actually needs — this is a chat about what to learn next, not a document.
MAX_HISTORY_TURNS = 20


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
    ) -> None:
        self._repository = repository
        self._llm_provider = llm_provider
        self._curriculum_service = curriculum_service
        self._revision_service = revision_service

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
        history = [
            ChatTurn(role="user" if m.role == ChatRole.USER else "assistant", content=m.content)
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
    ) -> AsyncIterator[dict]:
        # edit_learning_plan is only offered once a plan exists — there's nothing to edit
        # otherwise, and omitting it keeps the model from reaching for it prematurely.
        tools = (
            [GENERATE_PLAN_TOOL]
            + ([EDIT_PLAN_TOOL] if existing_plan else [])
            # Only offered when there's a record to look up. Fetching it on every turn would
            # be a wasted query on the many turns that never mention progress.
            + ([PRACTICE_RECORD_TOOL] if self._revision_service is not None and user_id else [])
        )
        request = ChatStreamRequest(
            system_prompt=chat_system_prompt(existing_plan),
            history=history,
            message=message,
            tools=tools,
        )
        text_parts: list[str] = []
        async for chunk in self._llm_provider.stream_chat(request):
            if chunk.text_delta:
                text_parts.append(chunk.text_delta)
                yield {"type": "text_delta", "delta": chunk.text_delta}
            if chunk.tool_call is not None and chunk.tool_call.name == "generate_learning_plan":
                async for event in self._handle_generate_plan(
                    session_id, chunk.tool_call.args, history, message, existing_plan
                ):
                    yield event
                return
            if chunk.tool_call is not None and chunk.tool_call.name == "edit_learning_plan":
                async for event in self._handle_edit_plan(
                    session_id, chunk.tool_call.args, history, message
                ):
                    yield event
                return
            if chunk.tool_call is not None and chunk.tool_call.name == "get_practice_record":
                async for event in self._handle_practice_record(
                    session_id, user_id, history, message, existing_plan
                ):
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

    async def _handle_generate_plan(
        self,
        session_id: str,
        args: dict,
        history: list[ChatTurn],
        user_message: str,
        existing_plan: bool,
    ) -> AsyncIterator[dict]:
        # Enforced here, not just in the prompt: a plan in a language the learner never
        # chose — or one the sandbox cannot run — is worse than no plan, and
        # asking-while-also-building reads as a contradiction. Nothing is persisted and no
        # "Generating..." note is shown.
        requested_language = (args.get("language") or "").strip().lower()
        try:
            language = Language(requested_language)
        except ValueError:
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
                )
            except Exception:
                logger.warning("Plan generation failed for session %s", session_id, exc_info=True)

        result_summary = (
            f"Generated a learning plan for '{plan.topic}' with {len(plan.nodes)} steps."
            if plan is not None
            else "Plan generation failed — tell the user something went wrong and they can try again."
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
        ):
            yield event

    async def _handle_edit_plan(
        self,
        session_id: str,
        args: dict,
        history: list[ChatTurn],
        user_message: str,
    ) -> AsyncIterator[dict]:
        label = "Updating your learning plan..."
        system_note = ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=ChatRole.SYSTEM,
            content=label,
            created_at=datetime.now(timezone.utc),
        )
        await self._repository.add_message(system_note)
        yield {"type": "tool_start", "label": label, "message_id": system_note.id}

        instruction = args.get("instruction") or user_message
        plan = None
        if self._curriculum_service is not None:
            try:
                # list_for_session is newest-first, so [0] is the session's active plan.
                plans = await self._curriculum_service.list_for_session(session_id)
                if plans:
                    plan = await self._curriculum_service.edit_plan(plans[0].id, instruction)
            except Exception:
                logger.warning("Plan edit failed for session %s", session_id, exc_info=True)

        if plan is not None:
            steps = ", ".join(
                f"{n.sequence_index + 1}. {n.skill_name or n.skill_id}" for n in plan.nodes
            )
            result_summary = f"Updated the plan. It now has {len(plan.nodes)} steps: {steps}."
            fallback = "I've updated your plan — open it with the corner button to see the changes."
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
        ):
            yield event

    async def _handle_practice_record(
        self,
        session_id: str,
        user_id: str | None,
        history: list[ChatTurn],
        user_message: str,
        existing_plan: bool,
    ) -> AsyncIterator[dict]:
        """Read-only lookup — nothing is persisted and no tool_start note is shown, because
        from the user's side this is the assistant answering, not doing."""
        candidates = []
        if self._revision_service is not None and user_id:
            try:
                candidates = await self._revision_service.get_revision_queue(user_id)
            except Exception:
                logger.warning("Failed to load the practice record for %s", user_id, exc_info=True)

        async for event in self._stream_tool_followup(
            session_id,
            history,
            user_message,
            existing_plan,
            "get_practice_record",
            mastery_context(candidates),
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
    ) -> AsyncIterator[dict]:
        """Feeds a tool's result back to the model for a natural closing line, streamed like
        any other reply, then persists it. Shared by every tool."""
        follow_up_request = ChatStreamRequest(
            system_prompt=chat_system_prompt(existing_plan),
            history=history + [ChatTurn(role="user", content=user_message)],
            message=(
                f"[{tool_name} tool result] {result_summary}\n\n"
                f"The tool has ALREADY run and this is its result. {instruction} Do not call "
                "any tool, and never output JSON, a function call, or code — only prose."
            ),
            tools=[],
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
            if chunk.done:
                break

        reply_text = "" if looks_like_tool_call else "".join(text_parts).strip()
        if not reply_text:
            reply_text = fallback_text
        reply = await self._persist_assistant_reply(session_id, reply_text)
        yield {
            "type": "done",
            "message_id": reply.id,
            "content": reply_text,
            "plan_id": plan_id,
        }

    async def _persist_assistant_reply(self, session_id: str, content: str) -> ChatMessage:
        reply = ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=ChatRole.ASSISTANT,
            content=content,
            created_at=datetime.now(timezone.utc),
        )
        await self._repository.add_message(reply)
        return reply
