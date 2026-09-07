-- Add evaluation test result columns directly into submissions table
ALTER TABLE submissions ADD COLUMN passed_tests INTEGER NOT NULL DEFAULT 0;
ALTER TABLE submissions ADD COLUMN total_tests INTEGER NOT NULL DEFAULT 0;
ALTER TABLE submissions ADD COLUMN runtime_ms REAL;
ALTER TABLE submissions ADD COLUMN memory_mb REAL;

-- Copy any legacy evaluation data into submissions if evaluations table exists
UPDATE submissions
SET
    passed_tests = COALESCE((SELECT e.passed_tests FROM evaluations e WHERE e.submission_id = submissions.id), 0),
    total_tests = COALESCE((SELECT e.total_tests FROM evaluations e WHERE e.submission_id = submissions.id), 0),
    runtime_ms = (SELECT e.runtime_ms FROM evaluations e WHERE e.submission_id = submissions.id),
    memory_mb = (SELECT e.memory_mb FROM evaluations e WHERE e.submission_id = submissions.id)
WHERE EXISTS (SELECT 1 FROM evaluations e WHERE e.submission_id = submissions.id);

-- Drop obsolete evaluations table
DROP TABLE IF EXISTS evaluations;

-- High-frequency query performance indexes
CREATE INDEX IF NOT EXISTS idx_problem_versions_problem ON problem_versions(problem_id);
CREATE INDEX IF NOT EXISTS idx_problem_examples_version ON problem_examples(problem_version_id);
CREATE INDEX IF NOT EXISTS idx_problem_tests_version ON problem_tests(problem_version_id);
CREATE INDEX IF NOT EXISTS idx_problem_sessions_user_problem ON problem_sessions(user_id, problem_id);
