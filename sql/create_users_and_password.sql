-- Create the two tables for a future login flow. No users are inserted here.
BEGIN;

CREATE TABLE IF NOT EXISTS users (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    thread_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
    create_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT users_username_valid CHECK (
        username <> '' AND username = BTRIM(username)
    )
);

-- 用户名保留注册时的写法，但不允许仅大小写不同的重复用户名。
CREATE UNIQUE INDEX IF NOT EXISTS users_username_lower_unique_idx ON users (LOWER(username));

-- Supports looking up the owner of a LangGraph thread ID.
CREATE INDEX IF NOT EXISTS users_thread_ids_gin_idx ON users USING GIN (thread_ids);

CREATE TABLE IF NOT EXISTS password (
    -- One credential row per user; the primary key also provides the user_id index.
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    -- Store a salted password hash here, never the original password.
    password_hash TEXT NOT NULL
);

-- 新会话使用首条提问命名；已有会话不补写标题。
CREATE TABLE IF NOT EXISTS chat_titles (
    thread_id UUID PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL CHECK (BTRIM(title) <> ''),
    create_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;
