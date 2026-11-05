-- 支持空数据库、旧版 flight_records 归档及新版表重复执行；不删除已有行。
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
DECLARE
    columns_found text[];
BEGIN
    IF to_regclass('public.flight_records') IS NOT NULL THEN
        SELECT array_agg(column_name::text) INTO columns_found
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'flight_records';
        IF ARRAY['uav_id', 'duration_minutes'] <@ columns_found THEN
            -- 已经是新版结构，不再次归档；下方会检查基础字段是否齐全。
            NULL;
        ELSIF ARRAY['flight_id', 'duration_seconds'] <@ columns_found THEN
            IF to_regclass('public.flight_records_legacy') IS NOT NULL THEN
                RAISE EXCEPTION 'flight_records_legacy 归档已存在，拒绝覆盖；请先核对两张旧表';
            END IF;
            ALTER TABLE public.flight_records RENAME TO flight_records_legacy;
        ELSE
            RAISE EXCEPTION '无法识别已有 flight_records 结构，拒绝自动切换；请先手动核对字段';
        END IF;
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS public.uavs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uav_code TEXT NOT NULL UNIQUE,
    uav_model TEXT NOT NULL,
    manufacturer TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS public.flight_records (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uav_id BIGINT NOT NULL REFERENCES public.uavs(id) ON DELETE RESTRICT,
    filename TEXT NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    duration_minutes NUMERIC(12, 2) NOT NULL CHECK (duration_minutes > 0),
    row_count INTEGER NOT NULL CHECK (row_count > 0),
    average_height DOUBLE PRECISION NOT NULL,
    max_height DOUBLE PRECISION NOT NULL,
    average_speed DOUBLE PRECISION NOT NULL,
    max_speed DOUBLE PRECISION NOT NULL,
    battery_start DOUBLE PRECISION NOT NULL,
    battery_end DOUBLE PRECISION NOT NULL,
    minimum_battery DOUBLE PRECISION NOT NULL,
    average_temperature DOUBLE PRECISION NOT NULL,
    max_temperature DOUBLE PRECISION NOT NULL,
    anomaly_status TEXT NOT NULL,
    anomaly_reason TEXT,
    version BIGINT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (end_time > start_time)
);

DO $$
DECLARE
    expected text[];
    missing_columns text[];
    relation_name text;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY['uavs', 'flight_records'] LOOP
        IF relation_name = 'uavs' THEN
            expected := ARRAY['id', 'uav_code', 'uav_model', 'manufacturer'];
        ELSE
            expected := ARRAY['id', 'uav_id', 'filename', 'start_time', 'end_time', 'duration_minutes',
                'row_count', 'average_height', 'max_height', 'average_speed', 'max_speed',
                'battery_start', 'battery_end', 'minimum_battery', 'average_temperature',
                'max_temperature', 'anomaly_status', 'anomaly_reason', 'version', 'created_at'];
        END IF;
        SELECT array_agg(required.name ORDER BY required.name) INTO missing_columns
        FROM unnest(expected) AS required(name)
        WHERE NOT EXISTS (
            SELECT 1 FROM information_schema.columns AS actual
            WHERE actual.table_schema = 'public' AND actual.table_name = relation_name
              AND actual.column_name = required.name
        );
        IF missing_columns IS NOT NULL THEN
            RAISE EXCEPTION '已有 % 表缺少基础字段：%，请先迁移现有表，脚本未删除数据', relation_name, missing_columns;
        END IF;
    END LOOP;
END
$$;

CREATE INDEX IF NOT EXISTS flight_records_uav_start_idx
ON public.flight_records (uav_id, start_time DESC, id DESC);
COMMIT;

