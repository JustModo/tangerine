import json
import aiosqlite

from app.sessions.domain.models import ChatMessage, LearningSession
from app.shared.database import connect


class SqliteSessionRepository:
    def __init__(self, database_path: str | None = None) -> None:
        self._database_path = database_path

    async def create(self, session: LearningSession) -> None:
        async with connect(self._database_path) as db:
            messages_json = json.dumps(
                [
                    {
                        "id": m.id,
                        "session_id": m.session_id,
                        "role": m.role.value,
                        "content": m.content,
                        "intent": m.intent,
                        "created_at": m.created_at.isoformat(),
                    }
                    for m in session.messages
                ]
            )
            await db.execute(
                "INSERT INTO learning_sessions (id, user_id, status, messages_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    session.id,
                    session.user_id,
                    session.status.value,
                    messages_json,
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
            return self._hydrate(row)

    async def list_for_user(self, user_id: str) -> list[LearningSession]:
        async with connect(self._database_path) as db:
            cursor = await db.execute(
                "SELECT * FROM learning_sessions WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            )
            rows = await cursor.fetchall()
            return [self._hydrate(row) for row in rows]

    async def add_message(self, message: ChatMessage) -> None:
        async with connect(self._database_path) as db:
            msg_dict = {
                "id": message.id,
                "session_id": message.session_id,
                "role": message.role.value,
                "content": message.content,
                "intent": message.intent,
                "created_at": message.created_at.isoformat(),
            }
            await db.execute(
                "UPDATE learning_sessions SET "
                "messages_json = json_insert(messages_json, '$[#]', json(?)), "
                "updated_at = ? WHERE id = ?",
                (json.dumps(msg_dict), message.created_at.isoformat(), message.session_id),
            )
            await db.commit()

    async def update_message_content(self, message_id: str, content: str) -> None:
        async with connect(self._database_path) as db:
            cursor = await db.execute(
                "SELECT id, messages_json FROM learning_sessions WHERE messages_json LIKE ?",
                (f"%{message_id}%",),
            )
            rows = await cursor.fetchall()
            for session_id, raw_json in rows:
                messages = json.loads(raw_json or "[]")
                modified = False
                for m in messages:
                    if m.get("id") == message_id:
                        m["content"] = content
                        modified = True
                        break
                if modified:
                    await db.execute(
                        "UPDATE learning_sessions SET messages_json = ? WHERE id = ?",
                        (json.dumps(messages), session_id),
                    )
            await db.commit()

    async def delete(self, session_id: str) -> None:
        async with connect(self._database_path) as db:
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
            await db.execute("DELETE FROM learning_sessions WHERE id = ?", (session_id,))
            await db.commit()

    def _hydrate(self, row: aiosqlite.Row) -> LearningSession:
        raw_messages = json.loads(row["messages_json"] or "[]")
        return LearningSession(
            id=row["id"],
            user_id=row["user_id"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            messages=[
                ChatMessage(
                    id=m["id"],
                    session_id=m.get("session_id", row["id"]),
                    role=m["role"],
                    content=m["content"],
                    intent=m.get("intent"),
                    created_at=m["created_at"],
                )
                for m in raw_messages
            ],
        )
