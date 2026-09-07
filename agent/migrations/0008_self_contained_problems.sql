-- Self-contained problems: collapse problem_versions, problem_examples, and problem_tests
-- directly into the problems table as structured JSON columns.
--
-- In an educational coding platform, a problem is a document asset with its statement,
-- harness, examples, and tests. Embedding these removes 3 tables and makes problem
-- retrieval and writes atomic single-row operations.

ALTER TABLE problems ADD COLUMN statement_md TEXT NOT NULL DEFAULT '';
ALTER TABLE problems ADD COLUMN reference_solution TEXT NOT NULL DEFAULT '';
ALTER TABLE problems ADD COLUMN user_code TEXT NOT NULL DEFAULT '';
ALTER TABLE problems ADD COLUMN pre_code TEXT NOT NULL DEFAULT '';
ALTER TABLE problems ADD COLUMN post_code TEXT NOT NULL DEFAULT '';
ALTER TABLE problems ADD COLUMN constraints TEXT;
ALTER TABLE problems ADD COLUMN input_format TEXT;
ALTER TABLE problems ADD COLUMN output_format TEXT;
ALTER TABLE problems ADD COLUMN hints_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE problems ADD COLUMN examples_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE problems ADD COLUMN tests_json TEXT NOT NULL DEFAULT '[]';

-- Backfill data from problem_versions, problem_examples, and problem_tests
UPDATE problems
SET
    statement_md = COALESCE((SELECT pv.statement_md FROM problem_versions pv WHERE pv.problem_id = problems.id ORDER BY pv.version DESC LIMIT 1), ''),
    reference_solution = COALESCE((SELECT pv.reference_solution FROM problem_versions pv WHERE pv.problem_id = problems.id ORDER BY pv.version DESC LIMIT 1), ''),
    user_code = COALESCE((SELECT pv.user_code FROM problem_versions pv WHERE pv.problem_id = problems.id ORDER BY pv.version DESC LIMIT 1), ''),
    pre_code = COALESCE((SELECT pv.pre_code FROM problem_versions pv WHERE pv.problem_id = problems.id ORDER BY pv.version DESC LIMIT 1), ''),
    post_code = COALESCE((SELECT pv.post_code FROM problem_versions pv WHERE pv.problem_id = problems.id ORDER BY pv.version DESC LIMIT 1), ''),
    constraints = (SELECT pv.constraints FROM problem_versions pv WHERE pv.problem_id = problems.id ORDER BY pv.version DESC LIMIT 1),
    input_format = (SELECT pv.input_format FROM problem_versions pv WHERE pv.problem_id = problems.id ORDER BY pv.version DESC LIMIT 1),
    output_format = (SELECT pv.output_format FROM problem_versions pv WHERE pv.problem_id = problems.id ORDER BY pv.version DESC LIMIT 1),
    hints_json = COALESCE((SELECT pv.hints_json FROM problem_versions pv WHERE pv.problem_id = problems.id ORDER BY pv.version DESC LIMIT 1), '[]'),
    examples_json = COALESCE((
        SELECT json_group_array(
            json_object(
                'id', pe.id,
                'input', pe.input,
                'output', pe.output,
                'explanation', pe.explanation
            )
        )
        FROM problem_examples pe
        WHERE pe.problem_version_id = (
            SELECT pv.id FROM problem_versions pv WHERE pv.problem_id = problems.id ORDER BY pv.version DESC LIMIT 1
        )
    ), '[]'),
    tests_json = COALESCE((
        SELECT json_group_array(
            json_object(
                'id', pt.id,
                'input', pt.input,
                'output_hash', pt.output_hash
            )
        )
        FROM problem_tests pt
        WHERE pt.problem_version_id = (
            SELECT pv.id FROM problem_versions pv WHERE pv.problem_id = problems.id ORDER BY pv.version DESC LIMIT 1
        )
    ), '[]');

DROP TABLE IF EXISTS problem_tests;
DROP TABLE IF EXISTS problem_examples;
DROP TABLE IF EXISTS problem_versions;
