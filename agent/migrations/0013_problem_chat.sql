-- Per-problem helper chat. Deliberately NOT chat_messages: that table is NOT NULL against
-- learning_sessions and its writer also bumps learning_sessions.updated_at, so reusing it
-- would drag code review into the learning-session transcript.
CREATE TABLE problem_chat_messages (
    id TEXT PRIMARY KEY,
    problem_session_id TEXT NOT NULL REFERENCES problem_sessions(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_problem_chat_messages_session ON problem_chat_messages(problem_session_id);
