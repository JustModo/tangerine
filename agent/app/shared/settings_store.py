"""Raw key/value access to `app_settings`.

Two callers store into this table — encrypted secrets and plain preferences — and both were
carrying an identical upsert. The encryption is the caller's business; the write is not.
"""

from app.shared.database import connect


async def read_setting(key: str) -> str | None:
    async with connect() as db:
        cursor = await db.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row[0] if row else None


async def write_setting(key: str, value: str) -> None:
    async with connect() as db:
        await db.execute(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value),
        )
        await db.commit()


async def delete_setting(key: str) -> None:
    async with connect() as db:
        await db.execute("DELETE FROM app_settings WHERE key = ?", (key,))
        await db.commit()
