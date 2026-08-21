ALTER TABLE problem_versions ADD COLUMN constraints TEXT;
ALTER TABLE problem_versions ADD COLUMN hints_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE problems ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]';
