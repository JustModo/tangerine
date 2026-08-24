-- A step that serves one EXISTING problem from the bank rather than selecting or generating
-- one. Set when a plan is built from problems the learner already has (flagged, solved) —
-- reopening the exact question, with no LLM call and no sandbox run.
ALTER TABLE lesson_nodes ADD COLUMN problem_id TEXT REFERENCES problems(id);
