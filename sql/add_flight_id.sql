-- 历史记录无法可靠还原 CSV 编号，保留 NULL；新导入由业务层提供编号。
BEGIN;
SET LOCAL lock_timeout = '10s';
ALTER TABLE public.flight_records ADD COLUMN IF NOT EXISTS flight_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS flight_records_user_flight_id_key
    ON public.flight_records (user_id, flight_id)
    WHERE flight_id IS NOT NULL;
COMMIT;
