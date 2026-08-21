import logging
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator

from app.curriculum.application.services import CurriculumService
from app.curriculum.domain.models import LessonPlanStatus
from app.llm.domain.provider import LLMProvider
from app.llm.domain.requests import ChatStreamRequest, ChatTurn
from app.llm.prompts.chat import GENERATE_PLAN_TOOL, chat_system_prompt
from app.sessions.domain.models import ChatMessage, ChatRole, LearningSession, SessionStatus
from app.sessions.domain.repository import SessionRepository
from app.shared.types import Language

logger = logging.getLogger(__name__)


class SessionService:
    """Session/chat persistence (plan.md §71-75). Chat is not the memory system — but a
    user message now gets a real, streamed assistant reply: the model itself decides,
    from conversation context, when to call the generate_learning_plan tool (no manual
    button, no static templated reply) — see add_message/_stream_reply."""

    def __init__(
        self,
        repository: SessionRepository,
        llm_provider: LLMProvider | None = None,
        curriculum_service: CurriculumService | None = None,
    ) -> None:
        self._repository = repository
        self._llm_provider = llm_provider
        self._curriculum_service = curriculum_service

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
        ]

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
                plans = await self._curriculum_service.list_for_session(session_id)
                existing_plan = any(
                    p.status in (LessonPlanStatus.DRAFT, LessonPlanStatus.ACCEPTED) for p in plans
                )
            except Exception:
                logger.warning("Failed to check for an existing plan for session %s", session_id, exc_info=True)

        try:
            async for event in self._stream_reply(session_id, history, content, existing_plan):
                yield event
        except Exception:
            logger.warning("Chat stream failed for session %s", session_id, exc_info=True)

    async def _stream_reply(
        self, session_id: str, history: list[ChatTurn], message: str, existing_plan: bool
    ) -> AsyncIterator[dict]:
        request = ChatStreamRequest(
            system_prompt=chat_system_prompt(existing_plan),
            history=history,
            message=message,
            tools=[GENERATE_PLAN_TOOL],
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
            if chunk.done:
                break

        reply_text = "".join(text_parts).strip()
        if reply_text:
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
        try:
            language = Language(args.get("language", Language.PYTHON.value))
        except ValueError:
            language = Language.PYTHON

        plan = None
        if self._curriculum_service is not None:
            try:
                plan = await self._curriculum_service.create_draft(session_id, topic, language, level)
            except Exception:
                logger.warning("Plan generation failed for session %s", session_id, exc_info=True)

        result_summary = (
            f"Generated a learning plan for '{plan.topic}' with {len(plan.nodes)} steps."
            if plan is not None
            else "Plan generation failed — tell the user something went wrong and they can try again."
        )
        follow_up_request = ChatStreamRequest(
            system_prompt=chat_system_prompt(existing_plan),
            history=history + [ChatTurn(role="user", content=user_message)],
            message=f"[generate_learning_plan tool result] {result_summary}",
            tools=[],
        )
        text_parts: list[str] = []
        async for chunk in self._llm_provider.stream_chat(follow_up_request):
            if chunk.text_delta:
                text_parts.append(chunk.text_delta)
                yield {"type": "text_delta", "delta": chunk.text_delta}
            if chunk.done:
                break

        reply_text = "".join(text_parts).strip() or (
            "Your learning plan is ready — check the corner button to view it."
            if plan is not None
            else "Something went wrong generating the plan — want to try again?"
        )
        reply = await self._persist_assistant_reply(session_id, reply_text)
        yield {
            "type": "done",
            "message_id": reply.id,
            "content": reply_text,
            "plan_id": plan.id if plan is not None else None,
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
