-- 任务 ID 同时作为 Celery 消息 ID 和数据库主键。
CREATE TABLE IF NOT EXISTS celery_task_states (
    task_id UUID PRIMARY KEY,
    user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    worker_id TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'RUNNING', 'COMMITTED', 'RETRY', 'SUCCESS', 'FAILED')),
    heartbeat TIMESTAMPTZ,
    lease_deadline TIMESTAMPTZ,
    -- CSV 入库与处理结果一同提交，用于消息重投后的安全恢复。
    result JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (
        (status IN ('PENDING', 'RETRY') AND worker_id IS NULL AND heartbeat IS NULL AND lease_deadline IS NULL)
        OR (status NOT IN ('PENDING', 'RETRY') AND worker_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS celery_task_states_lease_idx
    ON celery_task_states (lease_deadline)
    WHERE status IN ('RUNNING', 'COMMITTED');
