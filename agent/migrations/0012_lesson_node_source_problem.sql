-- Set only on the final node of a plan built around a problem the learner pasted in. When
-- that node is reached, the problem is adapted from THIS statement instead of being
-- invented from the skill name, so the course ends on the exact question they brought.
ALTER TABLE lesson_nodes ADD COLUMN source_problem_md TEXT;
