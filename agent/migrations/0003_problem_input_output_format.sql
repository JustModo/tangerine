-- Split out of statement_md into their own fields, same as constraints, so they render
-- as a distinct section instead of free-form prose the model could omit or duplicate.
ALTER TABLE problem_versions ADD COLUMN input_format TEXT;
ALTER TABLE problem_versions ADD COLUMN output_format TEXT;
