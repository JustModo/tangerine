CREATE TABLE llm_cache (
    cache_key TEXT PRIMARY KEY,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

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
