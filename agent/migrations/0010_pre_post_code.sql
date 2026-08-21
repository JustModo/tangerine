ALTER TABLE problem_versions ADD COLUMN pre_code TEXT NOT NULL DEFAULT '';
ALTER TABLE problem_versions ADD COLUMN post_code TEXT NOT NULL DEFAULT '';
-- boilerplate now holds only the user-editable function/class stub (ProblemVersion.user_code
-- in code); reference_solution now holds the fully assembled pre_code+reference_user_code+
-- post_code script, kept for audit only. Column names unchanged to avoid migration risk.
