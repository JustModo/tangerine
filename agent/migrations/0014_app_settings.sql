-- Runtime configuration supplied by the user through the web UI, as opposed to the fixed
-- deployment config in app/shared/config.py. Generic key/value so the next runtime-editable
-- value needs no migration. Values are encrypted (see app/shared/secrets.py).
CREATE TABLE app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
