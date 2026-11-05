-- 正式库、测试库均执行；保留无法确定归属的历史数据，查询层不会展示它们。
BEGIN;
SET LOCAL lock_timeout = '10s';
ALTER TABLE public.uavs ADD COLUMN IF NOT EXISTS user_id bigint;
ALTER TABLE public.flight_records ADD COLUMN IF NOT EXISTS user_id bigint;

-- 只接受各来源一致的任务所有者，归属冲突时不推测用户。
CREATE TEMP TABLE ownership_tasks ON COMMIT DROP AS
SELECT task_id, min(user_id) AS user_id FROM (
    SELECT task_id, user_id FROM public.celery_task_states
    UNION ALL SELECT task_id, user_id FROM public.csv_upload_idempotency_keys
    UNION ALL SELECT task_id, user_id FROM public.flight_report_idempotency_keys
) AS owners
WHERE user_id IS NOT NULL
GROUP BY task_id HAVING count(DISTINCT user_id) = 1;

WITH candidates AS (
    SELECT u.id, task.user_id FROM public.uavs AS u
    JOIN ownership_tasks AS task ON task.task_id = u.task_id
    UNION ALL
    SELECT f.uav_id, task.user_id FROM public.flight_records AS f
    JOIN ownership_tasks AS task ON task.task_id = f.task_id
), certain AS (
    SELECT id, min(user_id) AS user_id FROM candidates
    GROUP BY id HAVING count(DISTINCT user_id) = 1
)
UPDATE public.uavs AS u SET user_id = certain.user_id FROM certain
WHERE u.id = certain.id AND u.user_id IS NULL;

-- 不把同一飞行器下来源不明的历史记录自动分给某个用户。
UPDATE public.flight_records AS f SET user_id = task.user_id
FROM ownership_tasks AS task, public.uavs AS u
WHERE f.task_id = task.task_id AND f.uav_id = u.id
  AND u.user_id = task.user_id AND f.user_id IS NULL;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.uavs'::regclass AND conname = 'uavs_user_id_fkey') THEN
        ALTER TABLE public.uavs ADD CONSTRAINT uavs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE RESTRICT;
        ALTER TABLE public.uavs ADD CONSTRAINT uavs_id_user_id_key UNIQUE (id, user_id);
        ALTER TABLE public.flight_records ADD CONSTRAINT flight_records_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE RESTRICT;
        -- 数据库保证记录的用户和飞行器的用户相同，避免业务代码漏检后串写。
        ALTER TABLE public.flight_records ADD CONSTRAINT flight_records_uav_owner_fkey FOREIGN KEY (uav_id, user_id) REFERENCES public.uavs(id, user_id) ON DELETE RESTRICT;
        -- 不校验历史空归属行，但从现在起所有新增、更新行都必须有用户。
        ALTER TABLE public.uavs ADD CONSTRAINT uavs_new_rows_need_user CHECK (user_id IS NOT NULL) NOT VALID;
        ALTER TABLE public.flight_records ADD CONSTRAINT flight_records_new_rows_need_user CHECK (user_id IS NOT NULL) NOT VALID;
    END IF;
END
$$;
CREATE INDEX IF NOT EXISTS uavs_user_id_idx ON public.uavs(user_id, id);
CREATE INDEX IF NOT EXISTS flight_records_user_uav_start_idx ON public.flight_records(user_id, uav_id, start_time DESC, id DESC);
COMMIT;
