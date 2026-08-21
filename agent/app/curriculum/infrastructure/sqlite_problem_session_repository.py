import aiosqlite

from app.curriculum.domain.problem_session import ProblemSession
from app.shared.config import get_settings


class SqliteProblemSessionRepository:
    def __init__(self, database_path: str | None = None) -> None:
        self._database_path = database_path or get_settings().database_path

    async def save(self, session: ProblemSession) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute(
                "INSERT INTO problem_sessions "
                "(id, lesson_node_id, problem_id, user_id, code_path, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "code_path=excluded.code_path, status=excluded.status, updated_at=excluded.updated_at",
                (
                    session.id,
                    session.lesson_node_id,
                    session.problem_id,
                    session.user_id,
                    session.code_path,
                    session.status.value,
                    session.created_at.isoformat(),
                    session.updated_at.isoformat(),
                ),
            )
            await db.commit()

    async def get(self, session_id: str) -> ProblemSession | None:
        async with aiosqlite.connect(self._database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM problem_sessions WHERE id = ?", (session_id,))
            row = await cursor.fetchone()
            if row is None:
                return None
            return ProblemSession(
                id=row["id"],
                lesson_node_id=row["lesson_node_id"],
                problem_id=row["problem_id"],
                user_id=row["user_id"],
                code_path=row["code_path"],
                status=row["status"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
