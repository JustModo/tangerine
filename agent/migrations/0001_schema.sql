-- Tangerine schema, consolidated.
--
-- This replaces migrations 0001-0015, which were squashed once the incremental history
-- stopped being worth carrying. Columns that nothing read or wrote were dropped in the
-- squash rather than being ALTERed away: attempts (whole table, superseded by
-- submissions + evaluations), problem_sessions.code_path, evaluations.feedback,
-- evaluations.complexity_verdict, lesson_plans.status and users.email.
-- problem_versions.boilerplate was renamed to user_code, which is what the domain model
-- and the whole app have called it since the pre/user/post split.
--
-- Foreign keys are enforced on every connection (app/shared/database.py), so the
-- REFERENCES clauses below are real constraints, not documentation.

-- ---------------------------------------------------------------- identity

CREATE TABLE users (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE skills (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT
);

-- ---------------------------------------------------------------- problem bank

CREATE TABLE problems (
    id TEXT PRIMARY KEY,
    conceptual_id TEXT NOT NULL,
    title TEXT NOT NULL,
    language TEXT NOT NULL,
    difficulty TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'GENERATED',
    tags_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_problems_language ON problems(language);
CREATE INDEX idx_problems_status ON problems(status);

CREATE TABLE problem_skills (
    problem_id TEXT NOT NULL REFERENCES problems(id),
    skill_id TEXT NOT NULL REFERENCES skills(id),
    PRIMARY KEY (problem_id, skill_id)
);

CREATE INDEX idx_problem_skills_skill ON problem_skills(skill_id);

CREATE TABLE problem_versions (
    id TEXT PRIMARY KEY,
    problem_id TEXT NOT NULL REFERENCES problems(id),
    version INTEGER NOT NULL,
    statement_md TEXT NOT NULL,
    -- Never leaves the backend: handing it to the code helper would leak the answer.
    reference_solution TEXT NOT NULL,
    -- The three-part program. Only user_code is ever sent to the browser; pre_code and
    -- post_code are the harness that reads stdin and prints the result.
    user_code TEXT NOT NULL DEFAULT '',
    pre_code TEXT NOT NULL DEFAULT '',
    post_code TEXT NOT NULL DEFAULT '',
    constraints TEXT,
    hints_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE problem_examples (
    id TEXT PRIMARY KEY,
    problem_version_id TEXT NOT NULL REFERENCES problem_versions(id),
    input TEXT NOT NULL,
    output TEXT NOT NULL,
    explanation TEXT
);

CREATE TABLE problem_tests (
    id TEXT PRIMARY KEY,
    problem_version_id TEXT NOT NULL REFERENCES problem_versions(id),
    input TEXT NOT NULL,
    -- SHA-256 only. Expected output is never stored or transmitted in plaintext.
    output_hash TEXT NOT NULL,
    is_hidden INTEGER NOT NULL DEFAULT 1
);

-- ---------------------------------------------------------------- learning session + plan

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

CREATE INDEX idx_chat_messages_session ON chat_messages(session_id);

CREATE TABLE lesson_plans (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES learning_sessions(id),
    topic TEXT NOT NULL,
    language TEXT NOT NULL,
    level TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_lesson_plans_session ON lesson_plans(session_id);

CREATE TABLE lesson_nodes (
    id TEXT PRIMARY KEY,
    lesson_plan_id TEXT NOT NULL REFERENCES lesson_plans(id),
    skill_id TEXT NOT NULL REFERENCES skills(id),
    sequence_index INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'LOCKED',
    difficulty TEXT,
    -- Set when the learner pasted a problem in: the node is adapted from this statement
    -- rather than generated from the skill.
    source_problem_md TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_lesson_nodes_plan ON lesson_nodes(lesson_plan_id);

-- ---------------------------------------------------------------- solving a problem

CREATE TABLE problem_sessions (
    id TEXT PRIMARY KEY,
    lesson_node_id TEXT NOT NULL REFERENCES lesson_nodes(id),
    lesson_plan_id TEXT,
    problem_id TEXT NOT NULL REFERENCES problems(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    source_code TEXT,
    status TEXT NOT NULL DEFAULT 'NOT_STARTED',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_problem_sessions_node ON problem_sessions(lesson_node_id);

-- Deliberately not chat_messages: that table is NOT NULL against learning_sessions, and
-- its writer bumps learning_sessions.updated_at, so reusing it would drag code review into
-- the learning-session transcript.
CREATE TABLE problem_chat_messages (
    id TEXT PRIMARY KEY,
    problem_session_id TEXT NOT NULL REFERENCES problem_sessions(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_problem_chat_messages_session ON problem_chat_messages(problem_session_id);

-- ---------------------------------------------------------------- grading + mastery

CREATE TABLE submissions (
    id TEXT PRIMARY KEY,
    problem_id TEXT NOT NULL REFERENCES problems(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    code_snapshot TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_submissions_problem ON submissions(problem_id);

-- Per-test results are deliberately not persisted: they're returned to the client from
-- memory and are meaningless once the code changes.
CREATE TABLE evaluations (
    id TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL REFERENCES submissions(id),
    passed_tests INTEGER NOT NULL,
    total_tests INTEGER NOT NULL,
    runtime_ms REAL,
    memory_mb REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_evaluations_submission ON evaluations(submission_id);

CREATE TABLE user_skill_state (
    user_id TEXT NOT NULL REFERENCES users(id),
    skill_id TEXT NOT NULL REFERENCES skills(id),
    mastery_score REAL NOT NULL DEFAULT 0.0,
    streak INTEGER NOT NULL DEFAULT 0,
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, skill_id)
);

CREATE INDEX idx_user_skill_state_user ON user_skill_state(user_id);

-- ---------------------------------------------------------------- infrastructure

-- Background problem generation, so the bank already has a match by the time the learner
-- reaches the next node. Also prevents duplicate concurrent generation for one target.
CREATE TABLE generation_jobs (
    id TEXT PRIMARY KEY,
    skill_id TEXT NOT NULL,
    language TEXT NOT NULL,
    difficulty TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    problem_id TEXT,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_generation_jobs_lookup ON generation_jobs(skill_id, language, difficulty, status);

CREATE TABLE llm_cache (
    cache_key TEXT PRIMARY KEY,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_llm_cache_created_at ON llm_cache(created_at DESC);

-- Runtime configuration the user supplies through the web UI (currently just the Gemini
-- API key), as opposed to the fixed deployment config in app/shared/config.py. Values are
-- encrypted — see app/shared/secrets.py.
CREATE TABLE app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
