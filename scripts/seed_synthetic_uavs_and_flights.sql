-- One-time, deterministic synthetic data for the new uavs/flight_records tables.
-- Run with psql -v ON_ERROR_STOP=1. No old table is changed.
BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM uavs WHERE uav_code LIKE 'SIM-UAV-%')
       OR EXISTS (SELECT 1 FROM flight_records WHERE filename LIKE 'synthetic-flight-%') THEN
        RAISE EXCEPTION 'Synthetic UAV/flight seed already exists; nothing was added';
    END IF;
END $$;

INSERT INTO uavs (uav_code, uav_model, manufacturer)
SELECT
    'SIM-UAV-' || LPAD(number::text, 4, '0'),
    CASE number % 3
        WHEN 0 THEN 'SIM-INSPECTION-X4'
        WHEN 1 THEN 'SIM-SURVEY-M6'
        ELSE 'SIM-PATROL-Q8'
    END,
    CASE number % 3
        WHEN 0 THEN 'SIM-AERO'
        WHEN 1 THEN 'SIM-LABS'
        ELSE 'SIM-ROBOTICS'
    END
FROM generate_series(1, 300) AS series(number);

INSERT INTO flight_records (
    uav_id, filename, start_time, end_time, duration_minutes, row_count,
    average_height, max_height, average_speed, max_speed,
    battery_start, battery_end, minimum_battery,
    average_temperature, max_temperature, anomaly_status, anomaly_reason
)
SELECT
    uav.id,
    'synthetic-flight-' || LPAD(series.number::text, 4, '0') || '.csv',
    basis.started,
    basis.started + basis.duration_min * INTERVAL '1 minute',
    basis.duration_min,
    basis.duration_min, -- One synthetic measurement interval per minute.
    basis.average_height,
    metrics.max_height,
    basis.average_speed,
    metrics.max_speed,
    basis.battery_start,
    metrics.battery_end,
    metrics.minimum_battery,
    basis.average_temperature,
    metrics.max_temperature,
    CASE
        WHEN metrics.minimum_battery < 30
          OR (metrics.max_speed > 18 AND metrics.max_temperature > 38)
        THEN 'warning'
        ELSE 'normal'
    END,
    NULLIF(CONCAT_WS('；',
        CASE WHEN metrics.minimum_battery < 30 THEN '低电量' END,
        CASE WHEN metrics.max_speed > 18 AND metrics.max_temperature > 38
             THEN '高速且高温' END
    ), '')
FROM generate_series(1, 1000) AS series(number)
JOIN uavs AS uav ON uav.uav_code =
    'SIM-UAV-' || LPAD((((series.number - 1) % 300) + 1)::text, 4, '0')
CROSS JOIN LATERAL (
    SELECT
        12 + ((series.number * 37) % 109) AS duration_min,
        TIMESTAMPTZ '2026-01-01 08:00:00+08'
            + (series.number - 1) * INTERVAL '6 hours' AS started,
        35 + ((series.number * 17) % 76) + (series.number % 5) * 0.25 AS average_height,
        6 + ((series.number * 11) % 13) + (series.number % 4) * 0.20 AS average_speed,
        75 + ((series.number * 11) % 26) AS battery_start,
        20 + ((series.number * 7) % 16) + (series.number % 3) * 0.30 AS average_temperature
) AS basis
CROSS JOIN LATERAL (
    SELECT
        basis.average_height + 5 + ((series.number * 9) % 26) AS max_height,
        basis.average_speed + 2 + ((series.number * 7) % 10) AS max_speed,
        GREATEST(5, basis.battery_start - (
            5 + ROUND(basis.duration_min * (0.30 + (series.number % 5) * 0.035))::integer
        )) AS battery_end,
        basis.average_temperature + 2 + ((series.number * 5) % 7) AS max_temperature
) AS first_metrics
CROSS JOIN LATERAL (
    SELECT
        first_metrics.max_height,
        first_metrics.max_speed,
        first_metrics.battery_end,
        GREATEST(2, first_metrics.battery_end - (series.number % 6)) AS minimum_battery,
        first_metrics.max_temperature
) AS metrics;

DO $$
DECLARE
    uav_count integer;
    flight_count integer;
BEGIN
    SELECT COUNT(*) INTO uav_count FROM uavs WHERE uav_code LIKE 'SIM-UAV-%';
    SELECT COUNT(*) INTO flight_count FROM flight_records
    WHERE filename LIKE 'synthetic-flight-%';
    IF uav_count <> 300 OR flight_count <> 1000 THEN
        RAISE EXCEPTION 'Seed count mismatch: % UAVs and % flights', uav_count, flight_count;
    END IF;
    IF EXISTS (
        SELECT 1 FROM uavs AS uav
        LEFT JOIN flight_records AS flight ON flight.uav_id = uav.id
        WHERE uav.uav_code LIKE 'SIM-UAV-%'
        GROUP BY uav.id
        HAVING COUNT(flight.id) NOT BETWEEN 3 AND 4
    ) THEN
        RAISE EXCEPTION 'Each synthetic UAV must have 3 or 4 flights';
    END IF;
    IF EXISTS (
        SELECT 1 FROM flight_records
        WHERE filename LIKE 'synthetic-flight-%'
          AND (
              end_time <= start_time
              OR duration_minutes <> EXTRACT(EPOCH FROM end_time - start_time) / 60
              OR row_count <> duration_minutes
              OR max_height < average_height
              OR max_speed < average_speed
              OR max_temperature < average_temperature
              OR minimum_battery > battery_end
              OR battery_end > battery_start
              OR battery_start > 100
              OR (anomaly_status = 'warning' AND anomaly_reason IS NULL)
              OR (anomaly_status = 'normal' AND anomaly_reason IS NOT NULL)
          )
    ) THEN
        RAISE EXCEPTION 'Synthetic flight values are inconsistent';
    END IF;
END $$;

COMMIT;
