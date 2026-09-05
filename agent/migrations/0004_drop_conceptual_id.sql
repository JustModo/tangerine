-- Superseded by find_similar's fuzzy title match: the column was written on every save and
-- never read, compared or filtered on.
ALTER TABLE problems DROP COLUMN conceptual_id;
