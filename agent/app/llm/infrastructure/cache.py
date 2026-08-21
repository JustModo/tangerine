import hashlib

import aiosqlite

from app.shared.config import get_settings


def cache_key(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


class SqliteLLMCache:
    """Deterministic-generation cache keyed by prompt hash (plan.md §38). Only used for
    generation calls whose output only depends on the input (curriculum/problem) — never
    for per-submission coaching feedback, which plan.md explicitly warns against caching."""

    def __init__(self, database_path: str | None = None) -> None:
        self._database_path = database_path or get_settings().database_path

    async def get(self, key: str) -> str | None:
        async with aiosqlite.connect(self._database_path) as db:
            cursor = await db.execute(
                "SELECT response_json FROM llm_cache WHERE cache_key = ?", (key,)
            )
            row = await cursor.fetchone()
            return row[0] if row else None

    async def set(self, key: str, response_json: str) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute(
                "INSERT INTO llm_cache (cache_key, response_json) VALUES (?, ?) "
                "ON CONFLICT(cache_key) DO UPDATE SET response_json=excluded.response_json",
                (key, response_json),
            )
            await db.commit()
