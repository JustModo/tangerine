CREATE TABLE learning_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE chat_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES learning_sessions(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    intent TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE lesson_plans (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES learning_sessions(id),
    topic TEXT NOT NULL,
    language TEXT NOT NULL,
    level TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT',
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE lesson_nodes (
    id TEXT PRIMARY KEY,
    lesson_plan_id TEXT NOT NULL REFERENCES lesson_plans(id),
    skill_id TEXT NOT NULL REFERENCES skills(id),
    sequence_index INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'LOCKED',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE problem_sessions (
    id TEXT PRIMARY KEY,
    lesson_node_id TEXT NOT NULL REFERENCES lesson_nodes(id),
    problem_id TEXT NOT NULL REFERENCES problems(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    code_path TEXT,
    status TEXT NOT NULL DEFAULT 'NOT_STARTED',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_chat_messages_session ON chat_messages(session_id);
CREATE INDEX idx_lesson_plans_session ON lesson_plans(session_id);
CREATE INDEX idx_lesson_nodes_plan ON lesson_nodes(lesson_plan_id);
CREATE INDEX idx_problem_sessions_node ON problem_sessions(lesson_node_id);
