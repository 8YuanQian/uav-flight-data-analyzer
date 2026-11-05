-- 为现有数据库新增会话标题表，不修改已有会话和检查点。
BEGIN;

CREATE TABLE IF NOT EXISTS chat_titles (
    thread_id UUID PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL CHECK (BTRIM(title) <> ''),
    create_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;
