from app.shared.database import connect


async def read_setting(key: str, database_path: str | None = None) -> str | None:
    async with connect(database_path) as db:
        cursor = await db.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row[0] if row else None


async def write_setting(key: str, value: str, database_path: str | None = None) -> None:
    async with connect(database_path) as db:
        await db.execute(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value),
        )
        await db.commit()


async def delete_setting(key: str, database_path: str | None = None) -> None:
    async with connect(database_path) as db:
        await db.execute("DELETE FROM app_settings WHERE key = ?", (key,))
        await db.commit()
