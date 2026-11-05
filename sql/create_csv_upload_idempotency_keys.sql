-- 同一用户的同一幂等键只能提交一次 CSV 任务；不同用户可以使用相同的键。
CREATE TABLE IF NOT EXISTS csv_upload_idempotency_keys (
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    idempotency_key UUID NOT NULL,
    task_id UUID NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, idempotency_key)
);
