import aiosqlite

from app.shared.config import get_settings
from app.users.domain.models import LOCAL_USER_ID, User


class SqliteUserRepository:
    def __init__(self, database_path: str | None = None) -> None:
        self._database_path = database_path or get_settings().database_path

    async def ensure_default_user(self) -> User:
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO users (id, email) VALUES (?, NULL)", (LOCAL_USER_ID,)
            )
            await db.commit()
        return User(id=LOCAL_USER_ID)
