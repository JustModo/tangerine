import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from app.curriculum.application.problem_sessions import ProblemSessionService
from app.curriculum.application.services import CurriculumService
from app.curriculum.domain.models import LessonPlan
from app.llm.domain.provider import LLMProvider
from app.llm.domain.requests import ChatStreamRequest, ChatTurn
from app.llm.prompts.chat import chat_system_prompt
from app.llm.prompts.tools import FIND_PROBLEMS_TOOL, PRACTICE_RECORD_TOOL
from app.problems.application.library import ProblemLibraryService
from app.revision.application.services import RevisionService
from app.sessions.application.tool_registry import ToolRegistry
from app.sessions.domain.models import ChatMessage, ChatRole, LearningSession, SessionStatus
from app.sessions.domain.repository import SessionRepository
from app.sessions.tools import build_default_tools
from app.sessions.tools.base import ChatTool, ToolCallContext, ToolLabel
from app.shared.preferences import get_preferences

logger = logging.getLogger(__name__)

MAX_HISTORY_TURNS = 20
MAX_TOOL_CHAIN = 2
DEFAULT_FOLLOWUP_INSTRUCTION = (
    "Reply to the user in one or two plain sentences telling them what changed."
)


class SessionService:
    """Service managing chat sessions, LLM streaming, and tool execution."""

    def __init__(
        self,
        repository: SessionRepository,
        llm_provider: LLMProvider | None = None,
        curriculum_service: CurriculumService | None = None,
        revision_service: RevisionService | None = None,
        problem_session_service: ProblemSessionService | None = None,
        library_service: ProblemLibraryService | None = None,
    ) -> None:
        self._repository = repository
        self._llm_provider = llm_provider
        self._curriculum_service = curriculum_service
        self._tool_registry = ToolRegistry(
            build_default_tools(
                curriculum_service=curriculum_service,
                revision_service=revision_service,
                problem_session_service=problem_session_service,
                library_service=library_service,
            )
        )

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
                tool = self._tool_registry.get(chunk.tool_call.name)
                if tool is not None:
                    ctx = ToolCallContext(
                        session_id=session_id,
                        args=chunk.tool_call.args,
                        history=history,
                        message=message,
                        active_plan=active_plan,
                        user_id=user_id,
                        depth=depth,
                    )
                    async for event in self._run_tool(tool, ctx):
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
            has_record=self._tool_registry.get(PRACTICE_RECORD_TOOL.name) is not None
            and bool(user_id),
            has_library=self._tool_registry.get(FIND_PROBLEMS_TOOL.name) is not None
            and bool(user_id),
        )

    def _tools_for(self, active_plan: LessonPlan | None, user_id: str | None) -> list:
        return self._tool_registry.declarations_for(active_plan, user_id)

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

    async def _run_tool(
        self, tool: ChatTool, ctx: ToolCallContext, note_id: str | None = None
    ) -> AsyncIterator[dict]:
        """Stream a tool's progress labels, then the reply the model writes from its result."""
        result = None
        async for item in tool.execute(ctx):
            if isinstance(item, ToolLabel):
                if item.persist:
                    event = await self._announce(ctx.session_id, item.text, note_id)
                    note_id = event["message_id"]
                    yield event
                else:
                    yield {"type": "tool_start", "label": item.text}
            else:
                result = item
        if result is None:
            return

        async for event in self._stream_tool_followup(
            session_id=ctx.session_id,
            history=ctx.history,
            user_message=ctx.message,
            active_plan=result.active_plan or ctx.active_plan,
            user_id=ctx.user_id,
            tool_name=result.tool_name,
            result_summary=result.summary,
            fallback_text=result.fallback,
            plan_id=result.plan_id,
            instruction=result.instruction or DEFAULT_FOLLOWUP_INSTRUCTION,
            memo=result.memo,
            depth=ctx.depth,
            note_id=note_id,
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
        instruction: str = DEFAULT_FOLLOWUP_INSTRUCTION,
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
                chained_tool = self._tool_registry.get(chunk.tool_call.name)
                if chained_tool is not None:
                    chained_ctx = ToolCallContext(
                        session_id=session_id,
                        args=chunk.tool_call.args,
                        history=history,
                        message=chained_context,
                        active_plan=chain_plan,
                        user_id=user_id,
                        depth=depth + 1,
                    )
                    async for event in self._run_tool(chained_tool, chained_ctx, note_id):
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
