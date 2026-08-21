import logging
import uuid
from datetime import datetime, timezone

from app.llm.domain.provider import LLMProvider
from app.llm.graphs.intent import classify_intent
from app.llm.schemas.intent import ClassifiedIntent, UserIntent
from app.sessions.domain.models import ChatMessage, ChatRole, LearningSession, SessionStatus
from app.sessions.domain.repository import SessionRepository

logger = logging.getLogger(__name__)


class SessionService:
    """Session/chat persistence (plan.md §71-75). Chat is not the memory system — the
    classified `intent` on each message is the only structured state anything
    downstream relies on (plan.md §75) — but a classified message DOES get a real
    assistant reply (a clarifying question, or a confirm-before-generating summary),
    so the user is never asked to commit to a plan sight-unseen (plan.md §55)."""

    def __init__(self, repository: SessionRepository, llm_provider: LLMProvider | None = None) -> None:
        self._repository = repository
        self._llm_provider = llm_provider

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

    async def add_message(self, session_id: str, role: ChatRole, content: str) -> ChatMessage:
        classified = None
        if role == ChatRole.USER and self._llm_provider is not None:
            # Best-effort: a message is still worth recording even if the LLM is
            # unavailable/unconfigured (plan.md's "LLMs are not authoritative" theme).
            try:
                classified = await classify_intent(self._llm_provider, content)
            except Exception:
                logger.warning("Intent classification failed for session %s", session_id, exc_info=True)

        message = ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=role,
            content=content,
            intent=classified.intent.value if classified else None,
            created_at=datetime.now(timezone.utc),
        )
        await self._repository.add_message(message)

        # The reply lands after the user's own message is persisted, so the transcript
        # reads in the right order (a reply appearing before its trigger is confusing).
        if classified is not None:
            try:
                await self._reply(session_id, classified)
            except Exception:
                logger.warning("Assistant reply failed for session %s", session_id, exc_info=True)

        return message

    async def _reply(self, session_id: str, classified: ClassifiedIntent) -> None:
        if classified.intent == UserIntent.UNCLEAR:
            text = classified.clarifying_question or (
                'What would you like to learn? A broad topic (e.g. "prefix sums") works, '
                "or paste a specific problem you're stuck on."
            )
        elif classified.intent == UserIntent.LEARNING_PLAN:
            topic = classified.topic or "this topic"
            text = (
                f"Got it — I'll put together a learning plan for **{topic}**, in Python, "
                f"starting at beginner level: a short sequence of skills building from "
                f'fundamentals up to harder problems. Hit "Generate Learning Plan" below '
                f"to confirm, or send another message first if you'd like something "
                f"different — a different language, level, or focus."
            )
        else:  # SINGLE_PROBLEM — not built yet
            text = (
                "Practicing a single pasted problem isn't supported yet — let's build a "
                "learning plan instead. What topic would you like to learn?"
            )

        reply = ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=ChatRole.ASSISTANT,
            content=text,
            created_at=datetime.now(timezone.utc),
        )
        await self._repository.add_message(reply)
