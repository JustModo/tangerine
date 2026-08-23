"""A generic learner-preference registry, stored as plain values in `app_settings`
(the same key/value table `secrets.py` uses for the encrypted Gemini key).

Adding a future preference (e.g. a default difficulty) means adding one entry to
PREFERENCES — nothing else in this module, the settings endpoint, or the frontend
settings panel needs to change.
"""

from app.shared.database import connect
from app.shared.types import Language

PREFERENCES: dict[str, dict[str, object]] = {
    "default_language": {
        "options": [language.value for language in Language] + ["ask"],
        "default": "ask",
    },
}


async def get_preferences() -> dict[str, str]:
    async with connect() as db:
        cursor = await db.execute(
            "SELECT key, value FROM app_settings WHERE key IN "
            f"({','.join('?' for _ in PREFERENCES)})",
            list(PREFERENCES),
        )
        stored = {key: value async for key, value in cursor}
    return {key: stored.get(key, definition["default"]) for key, definition in PREFERENCES.items()}


async def set_preference(key: str, value: str) -> str:
    definition = PREFERENCES.get(key)
    if definition is None:
        raise ValueError(f"Unknown preference: {key}")
    if value not in definition["options"]:
        raise ValueError(f"'{value}' is not a valid value for {key}")
    async with connect() as db:
        await db.execute(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value),
        )
        await db.commit()
    return value
