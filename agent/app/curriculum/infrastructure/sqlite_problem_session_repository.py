import aiosqlite

from app.curriculum.domain.problem_chat import ProblemChatMessage
from app.curriculum.domain.problem_session import ProblemSession
from app.shared.config import get_settings
from app.shared.database import connect


class SqliteProblemSessionRepository:
    def __init__(self, database_path: str | None = None) -> None:
        self._database_path = database_path or get_settings().database_path

    async def save(self, session: ProblemSession) -> None:
        async with connect(self._database_path) as db:
            await db.execute(
                "INSERT INTO problem_sessions "
                "(id, lesson_node_id, lesson_plan_id, problem_id, user_id, source_code, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "source_code=excluded.source_code, status=excluded.status, updated_at=excluded.updated_at",
                (
                    session.id,
                    session.lesson_node_id,
                    session.lesson_plan_id,
                    session.problem_id,
                    session.user_id,
                    session.source_code,
                    session.status.value,
                    session.created_at.isoformat(),
                    session.updated_at.isoformat(),
                ),
            )
            await db.commit()

    async def get(self, session_id: str) -> ProblemSession | None:
        async with connect(self._database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM problem_sessions WHERE id = ?", (session_id,))
            row = await cursor.fetchone()
            return self._hydrate(row) if row else None

    async def get_by_node(self, lesson_node_id: str) -> ProblemSession | None:
        async with connect(self._database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM problem_sessions WHERE lesson_node_id = ? ORDER BY created_at DESC LIMIT 1",
                (lesson_node_id,),
            )
            row = await cursor.fetchone()
            return self._hydrate(row) if row else None

    async def add_chat_message(self, message: ProblemChatMessage) -> None:
        async with connect(self._database_path) as db:
            await db.execute(
                "INSERT INTO problem_chat_messages "
                "(id, problem_session_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    message.id,
                    message.problem_session_id,
                    message.role,
                    message.content,
                    message.created_at.isoformat(),
                ),
            )
            await db.commit()

    async def list_chat_messages(self, problem_session_id: str) -> list[ProblemChatMessage]:
        async with connect(self._database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM problem_chat_messages WHERE problem_session_id = ? "
                "ORDER BY created_at ASC",
                (problem_session_id,),
            )
            rows = await cursor.fetchall()
            return [
                ProblemChatMessage(
                    id=row["id"],
                    problem_session_id=row["problem_session_id"],
                    role=row["role"],
                    content=row["content"],
                    created_at=row["created_at"],
                )
                for row in rows
            ]

    def _hydrate(self, row: aiosqlite.Row) -> ProblemSession:
        return ProblemSession(
            id=row["id"],
            lesson_node_id=row["lesson_node_id"],
            lesson_plan_id=row["lesson_plan_id"],
            problem_id=row["problem_id"],
            user_id=row["user_id"],
            source_code=row["source_code"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
