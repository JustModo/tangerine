CREATE TABLE skills (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT
);

CREATE TABLE problems (
    id TEXT PRIMARY KEY,
    conceptual_id TEXT NOT NULL,
    title TEXT NOT NULL,
    language TEXT NOT NULL,
    difficulty TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'GENERATED',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE problem_versions (
    id TEXT PRIMARY KEY,
    problem_id TEXT NOT NULL REFERENCES problems(id),
    version INTEGER NOT NULL,
    statement_md TEXT NOT NULL,
    reference_solution TEXT NOT NULL,
    boilerplate TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE problem_skills (
    problem_id TEXT NOT NULL REFERENCES problems(id),
    skill_id TEXT NOT NULL REFERENCES skills(id),
    PRIMARY KEY (problem_id, skill_id)
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
    output_hash TEXT NOT NULL,
    is_hidden INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX idx_problems_status ON problems(status);
CREATE INDEX idx_problems_language ON problems(language);
CREATE INDEX idx_problem_skills_skill ON problem_skills(skill_id);
