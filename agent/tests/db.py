"""Test database helpers.

Foreign keys are now enforced on every connection (app/shared/database.py), so tests can no
longer insert a row whose parents don't exist — which is the point. These helpers seed the
minimum valid graph rather than making each test hand-roll its own INSERTs.
"""

import sqlite3

from app.shared.database import MIGRATIONS_DIR


def apply_migrations(db_path: str) -> None:
    """Records each file in schema_migrations exactly as run_migrations() does — otherwise
    a test that also boots the app re-runs every migration and dies on "table already
    exists"."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "filename TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        conn.executescript(path.read_text())
        conn.execute("INSERT INTO schema_migrations (filename) VALUES (?)", (path.name,))
    conn.commit()
    conn.close()


def seed_users(db_path: str, *user_ids: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT OR IGNORE INTO users (id) VALUES (?)", [(uid,) for uid in user_ids]
    )
    conn.commit()
    conn.close()


def seed_skills(db_path: str, *skill_ids: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT OR IGNORE INTO skills (id, name) VALUES (?, ?)",
        [(sid, sid) for sid in skill_ids],
    )
    conn.commit()
    conn.close()


def seed_lesson_node(
    db_path: str,
    node_id: str,
    *,
    user_id: str = "local-user",
    skill_id: str = "skill-1",
) -> None:
    """Creates the whole chain a problem_session needs: user -> learning_session ->
    lesson_plan -> lesson_node, plus the skill the node points at."""
    seed_users(db_path, user_id)
    seed_skills(db_path, skill_id)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT OR IGNORE INTO learning_sessions (id, user_id, status) VALUES (?, ?, 'ACTIVE')",
        (f"ls-{node_id}", user_id),
    )
    conn.execute(
        "INSERT OR IGNORE INTO lesson_plans (id, session_id, topic, language, level, version) "
        "VALUES (?, ?, 'topic', 'python', 'beginner', 1)",
        (f"lp-{node_id}", f"ls-{node_id}"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO lesson_nodes (id, lesson_plan_id, skill_id, sequence_index, status) "
        "VALUES (?, ?, ?, 0, 'AVAILABLE')",
        (node_id, f"lp-{node_id}", skill_id),
    )
    conn.commit()
    conn.close()
