import hashlib

from app.shared.config import get_settings
from app.shared.database import connect

MAX_ENTRIES = 5000


def cache_key(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


class SqliteLLMCache:
    """Deterministic-generation cache, keyed on caller-supplied semantic parts (see
    cache_key). Only used for generation whose output depends solely on its input —
    curricula, problems, lesson notes. Never for per-submission or per-conversation output,
    which is not deterministic and must not be replayed to a different learner."""

    def __init__(self, database_path: str | None = None) -> None:
        self._database_path = database_path or get_settings().database_path

    async def get(self, key: str) -> str | None:
        async with connect(self._database_path) as db:
            cursor = await db.execute(
                "SELECT response_json FROM llm_cache WHERE cache_key = ?", (key,)
            )
            row = await cursor.fetchone()
            return row[0] if row else None

    async def prune(self) -> int:
        """Keeps the newest MAX_ENTRIES rows. Keys are semantic, not prompt-content hashes,
        so a prompt revision leaves its old rows behind forever with nothing to evict them."""
        async with connect(self._database_path) as db:
            cursor = await db.execute(
                "DELETE FROM llm_cache WHERE cache_key NOT IN "
                "(SELECT cache_key FROM llm_cache ORDER BY created_at DESC LIMIT ?)",
                (MAX_ENTRIES,),
            )
            await db.commit()
            return cursor.rowcount

    async def set(self, key: str, response_json: str) -> None:
        async with connect(self._database_path) as db:
            await db.execute(
                "INSERT INTO llm_cache (cache_key, response_json) VALUES (?, ?) "
                "ON CONFLICT(cache_key) DO UPDATE SET response_json=excluded.response_json",
                (key, response_json),
            )
            await db.commit()
