CREATE TABLE attempts (
    id TEXT PRIMARY KEY,
    problem_id TEXT NOT NULL REFERENCES problems(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    execution_result_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE submissions (
    id TEXT PRIMARY KEY,
    problem_id TEXT NOT NULL REFERENCES problems(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    code_snapshot TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE evaluations (
    id TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL REFERENCES submissions(id),
    passed_tests INTEGER NOT NULL,
    total_tests INTEGER NOT NULL,
    runtime_ms REAL,
    memory_mb REAL,
    complexity_verdict TEXT,
    feedback TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_attempts_problem ON attempts(problem_id);
CREATE INDEX idx_submissions_problem ON submissions(problem_id);
CREATE INDEX idx_evaluations_submission ON evaluations(submission_id);
