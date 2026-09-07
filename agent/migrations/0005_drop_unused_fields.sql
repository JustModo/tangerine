-- Consolidated cleanup of unused / vestigial fields across tables:
-- 1. skills.description: never populated or read.
-- 2. problem_tests.is_hidden: redundant constant (grading tests are always hidden).
-- 3. evaluations.complexity_verdict: unneeded heuristic speed verdict.
-- 4. problem_versions.stress_input & stress_runtime_ms: unneeded stress test benchmarking data.

ALTER TABLE skills DROP COLUMN description;
ALTER TABLE problem_tests DROP COLUMN is_hidden;
ALTER TABLE evaluations DROP COLUMN complexity_verdict;
ALTER TABLE problem_versions DROP COLUMN stress_input;
ALTER TABLE problem_versions DROP COLUMN stress_runtime_ms;
