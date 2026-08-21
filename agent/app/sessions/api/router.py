from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from app.llm.infrastructure.gemini.provider import GeminiProvider
from app.sessions.application.services import SessionService
from app.sessions.domain.models import ChatMessage, ChatRole, LearningSession
from app.sessions.infrastructure.sqlite_repository import SqliteSessionRepository
from app.users.domain.models import LOCAL_USER_ID

router = APIRouter(prefix="/sessions", tags=["sessions"])


def get_service() -> SessionService:
    return SessionService(SqliteSessionRepository(), GeminiProvider())


class PostMessageBody(BaseModel):
    content: str


@router.post("")
async def create_session(service: SessionService = Depends(get_service)) -> LearningSession:
    return await service.create_session(user_id=LOCAL_USER_ID)


@router.get("")
async def list_sessions(service: SessionService = Depends(get_service)) -> list[LearningSession]:
    return await service.list_sessions(user_id=LOCAL_USER_ID)


@router.get("/{session_id}")
async def get_session(
    session_id: str, service: SessionService = Depends(get_service)
) -> LearningSession:
    session = await service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: str, service: SessionService = Depends(get_service)
) -> Response:
    if await service.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await service.delete_session(session_id)
    return Response(status_code=204)


@router.post("/{session_id}/messages")
async def post_message(
    session_id: str, body: PostMessageBody, service: SessionService = Depends(get_service)
) -> ChatMessage:
    if await service.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return await service.add_message(session_id, role=ChatRole.USER, content=body.content)
