-- 新任务记录关联登录用户；历史任务没有归属时保持 NULL。
BEGIN;

ALTER TABLE public.celery_task_states
    ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES public.users(id) ON DELETE SET NULL;

-- 同一用户的同一幂等键只能提交一份单条飞行报告任务。
CREATE TABLE IF NOT EXISTS public.flight_report_idempotency_keys (
    user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    idempotency_key UUID NOT NULL,
    record_id BIGINT NOT NULL,
    task_id UUID NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, idempotency_key)
);

COMMIT;
