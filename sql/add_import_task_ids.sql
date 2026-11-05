-- 已有飞行器及飞行记录保留原数据；历史行的 task_id 为 NULL。
-- task_id 标记写入来源，同一任务可以创建多架飞行器和多条飞行记录，因此不能对该列加唯一约束。
BEGIN;

ALTER TABLE public.uavs ADD COLUMN IF NOT EXISTS task_id UUID;
ALTER TABLE public.flight_records ADD COLUMN IF NOT EXISTS task_id UUID;

CREATE INDEX IF NOT EXISTS uavs_task_id_idx
    ON public.uavs (task_id) WHERE task_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS flight_records_task_id_idx
    ON public.flight_records (task_id) WHERE task_id IS NOT NULL;

COMMIT;
