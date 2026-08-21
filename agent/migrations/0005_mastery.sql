CREATE TABLE user_skill_state (
    user_id TEXT NOT NULL REFERENCES users(id),
    skill_id TEXT NOT NULL REFERENCES skills(id),
    mastery_score REAL NOT NULL DEFAULT 0.0,
    streak INTEGER NOT NULL DEFAULT 0,
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, skill_id)
);

CREATE INDEX idx_user_skill_state_user ON user_skill_state(user_id);
