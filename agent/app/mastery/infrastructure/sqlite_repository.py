from app.mastery.domain.models import UserSkillState
from app.shared.config import get_settings
from app.shared.database import connect


class SqliteUserSkillStateRepository:
    def __init__(self, database_path: str | None = None) -> None:
        self._database_path = database_path or get_settings().database_path

    async def get(self, user_id: str, skill_id: str) -> UserSkillState | None:
        async with connect(self._database_path) as db:
            cursor = await db.execute(
                "SELECT * FROM user_skill_state WHERE user_id = ? AND skill_id = ?",
                (user_id, skill_id),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return UserSkillState(
                user_id=row["user_id"],
                skill_id=row["skill_id"],
                mastery_score=row["mastery_score"],
                streak=row["streak"],
                last_seen_at=row["last_seen_at"],
            )

    async def save(self, state: UserSkillState) -> None:
        async with connect(self._database_path) as db:
            await db.execute(
                "INSERT INTO user_skill_state (user_id, skill_id, mastery_score, streak, last_seen_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id, skill_id) DO UPDATE SET "
                "mastery_score=excluded.mastery_score, streak=excluded.streak, last_seen_at=excluded.last_seen_at",
                (
                    state.user_id,
                    state.skill_id,
                    state.mastery_score,
                    state.streak,
                    state.last_seen_at.isoformat(),
                ),
            )
            await db.commit()

    async def list_for_user(self, user_id: str) -> list[UserSkillState]:
        async with connect(self._database_path) as db:
            cursor = await db.execute(
                "SELECT * FROM user_skill_state WHERE user_id = ?", (user_id,)
            )
            rows = await cursor.fetchall()
            return [
                UserSkillState(
                    user_id=row["user_id"],
                    skill_id=row["skill_id"],
                    mastery_score=row["mastery_score"],
                    streak=row["streak"],
                    last_seen_at=row["last_seen_at"],
                )
                for row in rows
            ]
