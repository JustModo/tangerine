import aiosqlite

from app.curriculum.domain.models import LessonNode, LessonNodeStatus, LessonPlan
from app.shared.config import get_settings


class SqliteLessonPlanRepository:
    def __init__(self, database_path: str | None = None) -> None:
        self._database_path = database_path or get_settings().database_path

    async def save(self, plan: LessonPlan) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute(
                "INSERT INTO lesson_plans (id, session_id, topic, language, level, status, version, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET status=excluded.status, version=excluded.version",
                (
                    plan.id,
                    plan.session_id,
                    plan.topic,
                    plan.language.value,
                    plan.level,
                    plan.status.value,
                    plan.version,
                    plan.created_at.isoformat(),
                ),
            )
            await db.commit()

    async def save_nodes(self, nodes: list[LessonNode]) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            for node in nodes:
                await db.execute(
                    "INSERT INTO lesson_nodes "
                    "(id, lesson_plan_id, skill_id, sequence_index, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        node.id,
                        node.lesson_plan_id,
                        node.skill_id,
                        node.sequence_index,
                        node.status.value,
                        node.created_at.isoformat(),
                    ),
                )
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
                "SELECT * FROM lesson_plans WHERE session_id = ? ORDER BY version DESC",
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
            status=row["status"],
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
                    created_at=n["created_at"],
                )
                for n in node_rows
            ],
        )
