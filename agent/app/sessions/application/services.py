import logging
import uuid
from datetime import datetime, timezone

from app.llm.domain.provider import LLMProvider
from app.llm.graphs.intent import classify_intent
from app.sessions.domain.models import ChatMessage, ChatRole, LearningSession, SessionStatus
from app.sessions.domain.repository import SessionRepository

logger = logging.getLogger(__name__)


class SessionService:
    """Session/chat persistence (plan.md §71-75). Chat is not the memory system — it's
    just a UI transcript; only the classified `intent` on each message is structured
    state anything downstream should rely on (plan.md §75)."""

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
        intent = None
        if role == ChatRole.USER and self._llm_provider is not None:
            # Best-effort: a message is still worth recording even if the LLM is
            # unavailable/unconfigured (plan.md's "LLMs are not authoritative" theme).
            try:
                classified = await classify_intent(self._llm_provider, content)
                intent = classified.intent.value
            except Exception:
                logger.warning("Intent classification failed for session %s", session_id, exc_info=True)

        message = ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=role,
            content=content,
            intent=intent,
            created_at=datetime.now(timezone.utc),
        )
        await self._repository.add_message(message)
        return message
