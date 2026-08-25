import aiosqlite

from app.sessions.domain.models import ChatMessage, LearningSession
from app.shared.config import get_settings
from app.shared.database import connect


class SqliteSessionRepository:
    def __init__(self, database_path: str | None = None) -> None:
        self._database_path = database_path or get_settings().database_path

    async def create(self, session: LearningSession) -> None:
        async with connect(self._database_path) as db:
            await db.execute(
                "INSERT INTO learning_sessions (id, user_id, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    session.id,
                    session.user_id,
                    session.status.value,
                    session.created_at.isoformat(),
                    session.updated_at.isoformat(),
                ),
            )
            await db.commit()

    async def get(self, session_id: str) -> LearningSession | None:
        async with connect(self._database_path) as db:
            cursor = await db.execute(
                "SELECT * FROM learning_sessions WHERE id = ?", (session_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return await self._hydrate(db, row)

    async def list_for_user(self, user_id: str) -> list[LearningSession]:
        async with connect(self._database_path) as db:
            cursor = await db.execute(
                "SELECT * FROM learning_sessions WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            )
            rows = await cursor.fetchall()
            return [await self._hydrate(db, row) for row in rows]

    async def add_message(self, message: ChatMessage) -> None:
        async with connect(self._database_path) as db:
            await db.execute(
                "INSERT INTO chat_messages (id, session_id, role, content, intent, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    message.id,
                    message.session_id,
                    message.role.value,
                    message.content,
                    message.intent,
                    message.created_at.isoformat(),
                ),
            )
            await db.execute(
                "UPDATE learning_sessions SET updated_at = ? WHERE id = ?",
                (message.created_at.isoformat(), message.session_id),
            )
            await db.commit()

    async def update_message_content(self, message_id: str, content: str) -> None:
        async with connect(self._database_path) as db:
            await db.execute(
                "UPDATE chat_messages SET content = ? WHERE id = ?",
                (content, message_id),
            )
            await db.commit()

    async def delete(self, session_id: str) -> None:
        async with connect(self._database_path) as db:
            # Helper-chat rows first — they hang off problem_sessions, so deleting the
            # sessions before them would orphan the conversation.
            await db.execute(
                "DELETE FROM problem_chat_messages WHERE problem_session_id IN ("
                "  SELECT id FROM problem_sessions WHERE lesson_node_id IN ("
                "    SELECT id FROM lesson_nodes WHERE lesson_plan_id IN ("
                "      SELECT id FROM lesson_plans WHERE session_id = ?)))",
                (session_id,),
            )
            await db.execute(
                "DELETE FROM problem_sessions WHERE lesson_node_id IN ("
                "  SELECT id FROM lesson_nodes WHERE lesson_plan_id IN ("
                "    SELECT id FROM lesson_plans WHERE session_id = ?))",
                (session_id,),
            )
            await db.execute(
                "DELETE FROM lesson_nodes WHERE lesson_plan_id IN ("
                "  SELECT id FROM lesson_plans WHERE session_id = ?)",
                (session_id,),
            )
            await db.execute("DELETE FROM lesson_plans WHERE session_id = ?", (session_id,))
            await db.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
            await db.execute("DELETE FROM learning_sessions WHERE id = ?", (session_id,))
            await db.commit()

    async def _hydrate(self, db: aiosqlite.Connection, row: aiosqlite.Row) -> LearningSession:
        cursor = await db.execute(
            "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC",
            (row["id"],),
        )
        message_rows = await cursor.fetchall()
        return LearningSession(
            id=row["id"],
            user_id=row["user_id"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            messages=[
                ChatMessage(
                    id=m["id"],
                    session_id=m["session_id"],
                    role=m["role"],
                    content=m["content"],
                    intent=m["intent"],
                    created_at=m["created_at"],
                )
                for m in message_rows
            ],
        )
