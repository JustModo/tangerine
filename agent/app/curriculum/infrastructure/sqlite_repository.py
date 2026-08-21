import aiosqlite

from app.curriculum.domain.models import LessonNode, LessonNodeStatus, LessonPlan
from app.shared.config import get_settings


_UPSERT_NODE_SQL = (
    "INSERT INTO lesson_nodes "
    "(id, lesson_plan_id, skill_id, sequence_index, status, difficulty, source_problem_md, created_at) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(id) DO UPDATE SET "
    "skill_id=excluded.skill_id, sequence_index=excluded.sequence_index, "
    "status=excluded.status, difficulty=excluded.difficulty, "
    "source_problem_md=excluded.source_problem_md"
)


def _node_params(node: LessonNode) -> tuple:
    return (
        node.id,
        node.lesson_plan_id,
        node.skill_id,
        node.sequence_index,
        node.status.value,
        node.difficulty,
        node.source_problem_md,
        node.created_at.isoformat(),
    )


class SqliteLessonPlanRepository:
    def __init__(self, database_path: str | None = None) -> None:
        self._database_path = database_path or get_settings().database_path

    async def save(self, plan: LessonPlan) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            # lesson_plans.status still exists in the schema with a DEFAULT — it's simply no
            # longer read or written, so no migration was needed to drop the concept.
            await db.execute(
                "INSERT INTO lesson_plans (id, session_id, topic, language, level, version, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET version=excluded.version",
                (
                    plan.id,
                    plan.session_id,
                    plan.topic,
                    plan.language.value,
                    plan.level,
                    plan.version,
                    plan.created_at.isoformat(),
                ),
            )
            await db.commit()

    async def save_nodes(self, nodes: list[LessonNode]) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            for node in nodes:
                await db.execute(_UPSERT_NODE_SQL, _node_params(node))
            await db.commit()

    async def replace_nodes(self, lesson_plan_id: str, nodes: list[LessonNode]) -> None:
        """Applies an edited node list, preserving the identity (and therefore the progress
        and problem sessions) of every node the caller chose to keep. Nodes absent from the
        new list are removed along with their problem sessions — the caller is responsible
        for never dropping a DONE node, so this only ever discards unstarted work."""
        keep_ids = [node.id for node in nodes]
        placeholders = ",".join("?" for _ in keep_ids) or "NULL"

        async with aiosqlite.connect(self._database_path) as db:
            # Helper-chat rows first — they hang off problem_sessions, so deleting the
            # sessions before them would orphan the conversation.
            await db.execute(
                f"DELETE FROM problem_chat_messages WHERE problem_session_id IN ("
                f"  SELECT id FROM problem_sessions WHERE lesson_node_id IN ("
                f"    SELECT id FROM lesson_nodes WHERE lesson_plan_id = ? AND id NOT IN ({placeholders})))",
                (lesson_plan_id, *keep_ids),
            )
            await db.execute(
                f"DELETE FROM problem_sessions WHERE lesson_node_id IN ("
                f"  SELECT id FROM lesson_nodes WHERE lesson_plan_id = ? AND id NOT IN ({placeholders}))",
                (lesson_plan_id, *keep_ids),
            )
            await db.execute(
                f"DELETE FROM lesson_nodes WHERE lesson_plan_id = ? AND id NOT IN ({placeholders})",
                (lesson_plan_id, *keep_ids),
            )
            for node in nodes:
                await db.execute(_UPSERT_NODE_SQL, _node_params(node))
            await db.commit()

    async def get(self, plan_id: str) -> LessonPlan | None:
        async with aiosqlite.connect(self._database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM lesson_plans WHERE id = ?", (plan_id,))
            row = await cursor.fetchone()
            return await self._hydrate(db, row) if row else None

    async def get_node(self, node_id: str) -> LessonNode | None:
        async with aiosqlite.connect(self._database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT n.*, s.name AS skill_name FROM lesson_nodes n "
                "JOIN skills s ON s.id = n.skill_id WHERE n.id = ?",
                (node_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return LessonNode(
                id=row["id"],
                lesson_plan_id=row["lesson_plan_id"],
                skill_id=row["skill_id"],
                skill_name=row["skill_name"],
                sequence_index=row["sequence_index"],
                status=row["status"],
                difficulty=row["difficulty"],
                source_problem_md=row["source_problem_md"],
                created_at=row["created_at"],
            )

    async def update_node_status(self, node_id: str, status: LessonNodeStatus) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute(
                "UPDATE lesson_nodes SET status = ? WHERE id = ?", (status.value, node_id)
            )
            await db.commit()

    async def unlock_next_node(self, lesson_plan_id: str, completed_sequence_index: int) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute(
                "UPDATE lesson_nodes SET status = ? "
                "WHERE lesson_plan_id = ? AND sequence_index = ? AND status = ?",
                (
                    LessonNodeStatus.AVAILABLE.value,
                    lesson_plan_id,
                    completed_sequence_index + 1,
                    LessonNodeStatus.LOCKED.value,
                ),
            )
            await db.commit()

    async def list_for_session(self, session_id: str) -> list[LessonPlan]:
        async with aiosqlite.connect(self._database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                # Newest first — the most recently generated plan is the session's active
                # one now that there's no ACCEPTED status to mark it (version is always 1,
                # so the old ORDER BY version DESC never actually ordered anything).
                "SELECT * FROM lesson_plans WHERE session_id = ? ORDER BY created_at DESC",
                (session_id,),
            )
            rows = await cursor.fetchall()
            return [await self._hydrate(db, row) for row in rows]

    async def _hydrate(self, db: aiosqlite.Connection, row: aiosqlite.Row) -> LessonPlan:
        cursor = await db.execute(
            "SELECT n.*, s.name AS skill_name FROM lesson_nodes n "
            "JOIN skills s ON s.id = n.skill_id "
            "WHERE n.lesson_plan_id = ? ORDER BY n.sequence_index ASC",
            (row["id"],),
        )
        node_rows = await cursor.fetchall()
        return LessonPlan(
            id=row["id"],
            session_id=row["session_id"],
            topic=row["topic"],
            language=row["language"],
            level=row["level"],
            version=row["version"],
            created_at=row["created_at"],
            nodes=[
                LessonNode(
                    id=n["id"],
                    lesson_plan_id=n["lesson_plan_id"],
                    skill_id=n["skill_id"],
                    skill_name=n["skill_name"],
                    sequence_index=n["sequence_index"],
                    status=n["status"],
                    difficulty=n["difficulty"],
                    source_problem_md=n["source_problem_md"],
                    created_at=n["created_at"],
                )
                for n in node_rows
            ],
        )
