-- Difficulty is now a real, editable property of a lesson step (the curriculum LLM already
-- generated it; it used to be discarded). NULL means "fall back to the mastery/position
-- guess in suggest_difficulty", which is what every pre-existing row does.
ALTER TABLE lesson_nodes ADD COLUMN difficulty TEXT;
