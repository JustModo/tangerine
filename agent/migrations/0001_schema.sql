-- Tangerine schema, consolidated.
--
-- This replaces migrations 0001-0015, squashed once the incremental history stopped being
-- worth carrying, plus the later learning-loop migrations folded in the same way while the
-- app is still pre-release. Columns that nothing read or wrote were dropped rather than
-- ALTERed away: attempts (whole table, superseded by submissions + evaluations),
-- problem_sessions.code_path, evaluations.feedback, lesson_plans.status and users.email.
-- generation_jobs went with the prefetch service: problems are generated when the learner
-- presses Start, never ahead of time.
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
    -- One input at the top of the stated constraint range, plus how long the reference
    -- solution took on it. A learner's runtime only means something against that baseline.
    -- Both null when the generator gave no stress input or it failed to run.
    stress_input TEXT,
    stress_runtime_ms REAL,
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
    -- Nullable: a practice session, started from the revision queue, belongs to a skill
    -- rather than to a step in a plan.
    lesson_node_id TEXT REFERENCES lesson_nodes(id),
    lesson_plan_id TEXT,
    problem_id TEXT NOT NULL REFERENCES problems(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    source_code TEXT,
    status TEXT NOT NULL DEFAULT 'NOT_STARTED',
    -- Learner-set "come back to this one".
    flagged INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_problem_sessions_node ON problem_sessions(lesson_node_id);
CREATE INDEX idx_problem_sessions_user ON problem_sessions(user_id);

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
    -- What the attempt cost the learner. Reported by the client: the server sees neither
    -- the editor clock nor which hints were revealed. Nullable, because a submission from
    -- a context that doesn't track them should say nothing rather than claim zero.
    duration_ms INTEGER,
    run_count INTEGER,
    hints_used INTEGER,
    helper_used INTEGER,
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
    -- 'optimal' | 'acceptable' | 'slow'. Null when the problem has no stress input, or the
    -- submission didn't pass every test: there is nothing to grade the speed of.
    complexity_verdict TEXT,
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
