import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from app.curriculum.domain.problem_chat import ProblemChatMessage
from app.curriculum.domain.problem_session_repository import ProblemSessionRepository
from app.llm.domain.provider import LLMProvider
from app.llm.domain.requests import ChatStreamRequest, ChatTurn
from app.llm.prompts.code_helper import CODE_HELPER_SYSTEM_PROMPT, code_helper_context
from app.problems.domain.repository import ProblemRepository
from app.shared.errors import NotFoundError

MAX_HISTORY_TURNS = 20

logger = logging.getLogger(__name__)


class CodeHelperService:
    """The coding page's helper chat. Streams like the main session chat, but scoped to a
    single problem and given the learner's own code plus their last test run as context.

    It is advisory only — no tools, so it can never mutate anything."""

    def __init__(
        self,
        session_repository: ProblemSessionRepository,
        problem_repository: ProblemRepository,
        llm_provider: LLMProvider,
    ) -> None:
        self._session_repository = session_repository
        self._problem_repository = problem_repository
        self._llm_provider = llm_provider

    async def get_session(self, problem_session_id: str):
        """Lets the route reject an unknown session with a real 404, before the streaming
        response has committed a 200 status line."""
        return await self._session_repository.get(problem_session_id)

    async def list_messages(self, problem_session_id: str) -> list[ProblemChatMessage]:
        return await self._session_repository.list_chat_messages(problem_session_id)

    async def send_message(
        self,
        problem_session_id: str,
        content: str,
        source_code: str,
        last_run: dict | None = None,
    ) -> AsyncIterator[dict]:
        session = await self._session_repository.get(problem_session_id)
        if session is None:
            raise NotFoundError(f"Problem session {problem_session_id} not found")

        problem = await self._problem_repository.get(session.problem_id)
        version = await self._problem_repository.get_latest_version(session.problem_id)
        if problem is None or version is None:
            raise NotFoundError(f"Problem {session.problem_id} not found")

        # Capped for the same reason as the main chat, and more urgently: each turn also
        # re-sends the full statement, the learner's whole file and the last test run.
        history = [
            ChatTurn(role=message.role, content=message.content)
            for message in await self.list_messages(problem_session_id)
        ][-MAX_HISTORY_TURNS:]

        now = datetime.now(UTC)
        user_message = ProblemChatMessage(
            id=str(uuid.uuid4()),
            problem_session_id=problem_session_id,
            role="user",
            content=content,
            created_at=now,
        )
        await self._session_repository.add_chat_message(user_message)
        yield {"type": "user_message", "message_id": user_message.id}

        # Only fields the browser already holds go into the context. version.reference_solution,
        # version.tests and version.pre_code/post_code are deliberately never passed.
        context = code_helper_context(
            title=problem.title,
            language=problem.language.value,
            difficulty=problem.difficulty,
            statement_md=version.statement_md,
            constraints=version.constraints,
            input_format=version.input_format,
            output_format=version.output_format,
            examples=[
                {"input": example.input, "output": example.output} for example in version.examples
            ],
            starter_code=version.user_code,
            source_code=source_code,
            last_run=last_run,
        )

        # The static rules stay alone as the system prompt so they form a byte-identical
        # prefix Gemini can bill at the cached rate; the context changes every turn (the
        # learner's file above all), and concatenating the two made the whole 5KB look
        # new each time. It rides with the message instead, where it belongs anyway.
        request = ChatStreamRequest(
            system_prompt=CODE_HELPER_SYSTEM_PROMPT,
            history=history,
            message=f"{context}\n\n{content}",
        )

        text_parts: list[str] = []
        try:
            async for chunk in self._llm_provider.stream_chat(request):
                if chunk.text_delta:
                    text_parts.append(chunk.text_delta)
                    yield {"type": "text_delta", "delta": chunk.text_delta}
                if chunk.done:
                    break
        except Exception:
            logger.warning("Code helper stream failed for %s", problem_session_id, exc_info=True)

        reply_text = "".join(text_parts).strip()
        if not reply_text:
            reply_text = "Something went wrong on my end — try asking again."

        reply = ProblemChatMessage(
            id=str(uuid.uuid4()),
            problem_session_id=problem_session_id,
            role="assistant",
            content=reply_text,
            created_at=datetime.now(UTC),
        )
        await self._session_repository.add_chat_message(reply)
        yield {"type": "done", "message_id": reply.id, "content": reply_text}
