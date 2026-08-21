"""Runtime secrets the user supplies through the web UI, encrypted at rest.

The encryption key lives in a file beside the SQLite database, so under Docker it lands on
the same `agent-data` volume and survives restarts. This protects DB dumps and backups —
it is NOT protection against someone who already has the volume.
"""

from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.shared.config import get_settings
from app.shared.database import connect

GEMINI_API_KEY = "gemini_api_key"


def _key_file() -> Path:
    return Path(get_settings().database_path).resolve().parent / "secret.key"


def _fernet() -> Fernet:
    path = _key_file()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write then chmod rather than os.open(mode=) so the intent is obvious; the window
        # is a single statement on a directory only this process writes to.
        path.write_bytes(Fernet.generate_key())
        path.chmod(0o600)
    return Fernet(path.read_bytes())


async def read_secret(key: str) -> str | None:
    async with connect() as db:
        cursor = await db.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
    if row is None:
        return None
    try:
        return _fernet().decrypt(row[0].encode()).decode()
    except InvalidToken:
        # secret.key was replaced or lost — treat the stored value as gone rather than
        # crashing every request; the user can re-enter it through the setup screen.
        return None


async def write_secret(key: str, value: str) -> None:
    encrypted = _fernet().encrypt(value.encode()).decode()
    async with connect() as db:
        await db.execute(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, encrypted),
        )
        await db.commit()


async def delete_secret(key: str) -> None:
    async with connect() as db:
        await db.execute("DELETE FROM app_settings WHERE key = ?", (key,))
        await db.commit()


async def get_gemini_api_key() -> str | None:
    """Resolved at every call — deliberately not cached, so a key saved through the setup
    screen takes effect on the very next request with no restart. Env wins so that a dev
    .env keeps working exactly as before."""
    return get_settings().gemini_api_key or await read_secret(GEMINI_API_KEY)


async def set_gemini_api_key(value: str) -> None:
    await write_secret(GEMINI_API_KEY, value)


async def clear_gemini_api_key() -> None:
    await delete_secret(GEMINI_API_KEY)


async def gemini_key_status() -> dict[str, object]:
    """Safe to serialise to the browser — the plaintext key never leaves this module."""
    env_key = get_settings().gemini_api_key
    key = env_key or await read_secret(GEMINI_API_KEY)
    return {
        "configured": bool(key),
        "source": ("env" if env_key else "stored") if key else None,
        "masked": f"...{key[-4:]}" if key else None,
    }
