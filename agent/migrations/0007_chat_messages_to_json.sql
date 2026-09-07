-- Migrate chat history from separate tables into JSON array columns on parent sessions
ALTER TABLE learning_sessions ADD COLUMN messages_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE problem_sessions ADD COLUMN messages_json TEXT NOT NULL DEFAULT '[]';

-- Backfill learning_sessions messages if chat_messages table exists
UPDATE learning_sessions
SET messages_json = COALESCE(
    (
        SELECT json_group_array(
            json_object(
                'id', id,
                'session_id', session_id,
                'role', role,
                'content', content,
                'intent', intent,
                'created_at', created_at
            )
        )
        FROM (SELECT * FROM chat_messages WHERE session_id = learning_sessions.id ORDER BY created_at ASC)
    ),
    '[]'
)
WHERE EXISTS (SELECT 1 FROM sqlite_master WHERE type='table' AND name='chat_messages');

-- Backfill problem_sessions messages if problem_chat_messages table exists
UPDATE problem_sessions
SET messages_json = COALESCE(
    (
        SELECT json_group_array(
            json_object(
                'id', id,
                'problem_session_id', problem_session_id,
                'role', role,
                'content', content,
                'created_at', created_at
            )
        )
        FROM (SELECT * FROM problem_chat_messages WHERE problem_session_id = problem_sessions.id ORDER BY created_at ASC)
    ),
    '[]'
)
WHERE EXISTS (SELECT 1 FROM sqlite_master WHERE type='table' AND name='problem_chat_messages');

-- Drop obsolete message tables
DROP TABLE IF EXISTS chat_messages;
DROP TABLE IF EXISTS problem_chat_messages;
