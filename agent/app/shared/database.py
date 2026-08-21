import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from app.shared.config import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"

_PRAGMAS = (
    "PRAGMA foreign_keys = ON",
    "PRAGMA journal_mode = WAL",
    "PRAGMA busy_timeout = 5000",
)


def get_connection() -> sqlite3.Connection:
    """Synchronous connection — migrations only. Request paths use `connect()` instead."""
    conn = sqlite3.connect(get_settings().database_path)
    for pragma in _PRAGMAS:
        conn.execute(pragma)
    return conn


@asynccontextmanager
async def connect(database_path: str | None = None):
    """The async connection every repository must use. Drop-in for
    `async with aiosqlite.connect(path) as db`, minus the missing pragmas."""
    async with aiosqlite.connect(database_path or get_settings().database_path) as db:
        for pragma in _PRAGMAS:
            await db.execute(pragma)
        yield db


def run_migrations() -> list[str]:
    """Apply any .sql files under migrations/ not yet recorded in schema_migrations, in filename order."""
    conn = get_connection()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "filename TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        applied = {row[0] for row in conn.execute("SELECT filename FROM schema_migrations")}

        newly_applied = []
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in applied:
                continue
            conn.executescript(path.read_text())
            conn.execute("INSERT INTO schema_migrations (filename) VALUES (?)", (path.name,))
            conn.commit()
            newly_applied.append(path.name)
        return newly_applied
    finally:
        conn.close()
