import uuid

from app.shared.config import get_settings
from app.shared.database import connect


class SqliteSkillRepository:
    def __init__(self, database_path: str | None = None) -> None:
        self._database_path = database_path or get_settings().database_path

    async def ensure_skill(self, name: str) -> str:
        """Find-or-create a skill by name, returning its id. Normalised because the UNIQUE
        constraint is byte-exact while every caller compares with .strip().lower()."""
        name = " ".join(name.split()).lower()
        async with connect(self._database_path) as db:
            cursor = await db.execute("SELECT id FROM skills WHERE name = ?", (name,))
            row = await cursor.fetchone()
            if row:
                return row[0]
            skill_id = str(uuid.uuid4())
            await db.execute("INSERT INTO skills (id, name) VALUES (?, ?)", (skill_id, name))
            await db.commit()
            return skill_id

    async def list_all(self) -> list[tuple[str, str]]:
        """Every (id, name), for resolving a skill the user named in prose — the chat agent
        knows "graphs", not a UUID."""
        async with connect(self._database_path) as db:
            cursor = await db.execute("SELECT id, name FROM skills")
            return [(row[0], row[1]) for row in await cursor.fetchall()]

    async def names(self) -> dict[str, str]:
        """Every skill id to its name, in one query. `skills` is a tiny near-static table,
        so a caller naming a page's worth of them should read it once, not once per row."""
        return dict(await self.list_all())

    async def get_name(self, skill_id: str) -> str | None:
        async with connect(self._database_path) as db:
            cursor = await db.execute("SELECT name FROM skills WHERE id = ?", (skill_id,))
            row = await cursor.fetchone()
            return row[0] if row else None
