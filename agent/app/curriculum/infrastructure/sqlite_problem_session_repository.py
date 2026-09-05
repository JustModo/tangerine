import aiosqlite

from app.curriculum.domain.problem_chat import ProblemChatMessage
from app.curriculum.domain.problem_session import ProblemSession
from app.shared.database import connect


class SqliteProblemSessionRepository:
    def __init__(self, database_path: str | None = None) -> None:
        self._database_path = database_path

    async def save(self, session: ProblemSession) -> None:
        async with connect(self._database_path) as db:
            await db.execute(
                "INSERT INTO problem_sessions "
                "(id, lesson_node_id, lesson_plan_id, problem_id, user_id, source_code, "
                "status, flagged, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                # Every column except the identity ones (id, problem_id, user_id,
                # created_at) is mutable. lesson_node_id/lesson_plan_id in particular:
                # attaching a node-less session to a plan step is an update, and leaving
                # them out meant the write silently did nothing while reporting success.
                "ON CONFLICT(id) DO UPDATE SET "
                "lesson_node_id=excluded.lesson_node_id, "
                "lesson_plan_id=excluded.lesson_plan_id, "
                "source_code=excluded.source_code, status=excluded.status, "
                "flagged=excluded.flagged, updated_at=excluded.updated_at",
                (
                    session.id,
                    session.lesson_node_id,
                    session.lesson_plan_id,
                    session.problem_id,
                    session.user_id,
                    session.source_code,
                    session.status.value,
                    int(session.flagged),
                    session.created_at.isoformat(),
                    session.updated_at.isoformat(),
                ),
            )
            await db.commit()

    async def get(self, session_id: str) -> ProblemSession | None:
        async with connect(self._database_path) as db:
            cursor = await db.execute("SELECT * FROM problem_sessions WHERE id = ?", (session_id,))
            row = await cursor.fetchone()
            return self._hydrate(row) if row else None

    async def get_by_node(self, lesson_node_id: str) -> ProblemSession | None:
        async with connect(self._database_path) as db:
            cursor = await db.execute(
                "SELECT * FROM problem_sessions WHERE lesson_node_id = ? ORDER BY created_at DESC LIMIT 1",
                (lesson_node_id,),
            )
            row = await cursor.fetchone()
            return self._hydrate(row) if row else None

    async def find_for_problem(self, user_id: str, problem_id: str) -> ProblemSession | None:
        """An existing session for this exact problem, so opening it from the "all
        problems" list resumes rather than orphaning progress with a duplicate row."""
        async with connect(self._database_path) as db:
            cursor = await db.execute(
                "SELECT * FROM problem_sessions WHERE user_id = ? AND problem_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (user_id, problem_id),
            )
            row = await cursor.fetchone()
            return self._hydrate(row) if row else None

    async def delete_unsubmitted_for_node(self, lesson_node_id: str) -> None:
        """Discards this node's session if it's NOT_STARTED/IN_PROGRESS — neither has been
        submitted for grading, so nothing graded is lost. A SUBMITTED (failed) or COMPLETED
        session is real, graded work and is left untouched.

        The single primitive behind "the problem a node would generate no longer matches
        what's selected" — used whenever an edit changes what a node's problem should be
        (the plan's language, or that node's difficulty): without it, next_problem's
        get_by_node short-circuit would keep resurfacing the stale problem forever, even for
        an in-progress attempt the learner realizes no longer fits."""
        async with connect(self._database_path) as db:
            await db.execute(
                "DELETE FROM problem_chat_messages WHERE problem_session_id IN ("
                "SELECT id FROM problem_sessions WHERE lesson_node_id = ? AND status IN (?, ?))",
                (lesson_node_id, "NOT_STARTED", "IN_PROGRESS"),
            )
            await db.execute(
                "DELETE FROM problem_sessions WHERE lesson_node_id = ? AND status IN (?, ?)",
                (lesson_node_id, "NOT_STARTED", "IN_PROGRESS"),
            )
            await db.commit()

    async def list_problem_ids_for_user(self, user_id: str) -> list[str]:
        """Everything this learner has already been served, so selection never hands back a
        problem they have seen."""
        async with connect(self._database_path) as db:
            cursor = await db.execute(
                "SELECT DISTINCT problem_id FROM problem_sessions WHERE user_id = ?", (user_id,)
            )
            return [row[0] for row in await cursor.fetchall()]

    async def list_for_user(self, user_id: str) -> list[ProblemSession]:
        async with connect(self._database_path) as db:
            cursor = await db.execute(
                "SELECT * FROM problem_sessions WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            )
            return [self._hydrate(row) for row in await cursor.fetchall()]

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
            flagged=bool(row["flagged"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
