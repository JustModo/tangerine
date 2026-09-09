from app.shared.database import connect
from app.shared.settings_store import write_setting
from app.shared.types import Language

PREFERENCES: dict[str, dict[str, object]] = {
    "default_language": {
        "options": [language.value for language in Language] + ["ask"],
        "default": "ask",
    },
}


async def get_preferences(database_path: str | None = None) -> dict[str, str]:
    async with connect(database_path) as db:
        cursor = await db.execute(
            "SELECT key, value FROM app_settings WHERE key IN "
            f"({','.join('?' for _ in PREFERENCES)})",
            list(PREFERENCES),
        )
        stored = {key: value async for key, value in cursor}
    return {key: stored.get(key, definition["default"]) for key, definition in PREFERENCES.items()}


async def set_preference(key: str, value: str, database_path: str | None = None) -> str:
    definition = PREFERENCES.get(key)
    if definition is None:
        raise ValueError(f"Unknown preference: {key}")
    if value not in definition["options"]:
        raise ValueError(f"'{value}' is not a valid value for {key}")
    await write_setting(key, value, database_path=database_path)
    return value
