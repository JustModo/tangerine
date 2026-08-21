import sqlite3
from pathlib import Path

from app.shared.config import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def get_connection() -> sqlite3.Connection:
    settings = get_settings()
    conn = sqlite3.connect(settings.database_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


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
