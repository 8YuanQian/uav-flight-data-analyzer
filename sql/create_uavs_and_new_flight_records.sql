-- One-time schema switch. It keeps both old tables and every old row intact.
-- Run only after deploying code that reads the new flight_records structure.
BEGIN;

ALTER TABLE flight_records RENAME TO flight_records_legacy;

CREATE TABLE uavs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uav_code TEXT NOT NULL UNIQUE,
    uav_model TEXT NOT NULL,
    manufacturer TEXT NOT NULL
);

CREATE TABLE flight_records (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uav_id BIGINT NOT NULL REFERENCES uavs(id) ON DELETE RESTRICT,
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

CREATE INDEX flight_records_uav_start_idx
ON flight_records (uav_id, start_time DESC, id DESC);

COMMIT;
