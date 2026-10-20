"""在已有 uav_project 数据库中建表，并插入 100 条模拟飞行记录。"""

import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psycopg


# 同时支持 python scripts/init_flight_records.py 和 python -m scripts.init_flight_records。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.database import get_connection


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS flight_records (
    id BIGSERIAL PRIMARY KEY,
    flight_id TEXT NOT NULL UNIQUE,
    drone_id TEXT,
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    duration_seconds INTEGER,
    average_height FLOAT,
    max_height FLOAT,
    average_speed FLOAT,
    max_speed FLOAT,
    battery_start FLOAT,
    battery_end FLOAT,
    average_temperature FLOAT,
    anomaly_status TEXT,
    anomaly_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
)
"""

INSERT_FLIGHT_SQL = """
INSERT INTO flight_records (
    flight_id, drone_id, start_time, end_time, duration_seconds,
    average_height, max_height, average_speed, max_speed,
    battery_start, battery_end, average_temperature,
    anomaly_status, anomaly_reason
) VALUES (
    %(flight_id)s, %(drone_id)s, %(start_time)s, %(end_time)s,
    %(duration_seconds)s, %(average_height)s, %(max_height)s,
    %(average_speed)s, %(max_speed)s, %(battery_start)s,
    %(battery_end)s, %(average_temperature)s, %(anomaly_status)s,
    %(anomaly_reason)s
)
ON CONFLICT (flight_id) DO NOTHING
"""


def generate_mock_flights(seed: int | None = None) -> list[dict[str, Any]]:
    """随机生成 100 条记录，15% 异常；可传 seed 复现模拟数据。"""
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    records = []
    # 随机选择异常位置，每种异常各 5 条，保证三类异常都出现。
    anomaly_types = {
        index: anomaly_type % 3
        for anomaly_type, index in enumerate(rng.sample(range(100), 15))
    }

    for index in range(100):
        start_time = now - timedelta(hours=(99 - index) * 6 + 1)
        duration_seconds = rng.randint(300, 1800)
        average_height = round(rng.uniform(50, 135), 2)
        max_height = round(rng.uniform(average_height, 150), 2)
        average_speed = round(rng.uniform(5, 20), 2)
        max_speed = round(rng.uniform(average_speed, 25), 2)
        battery_end = round(rng.uniform(20, 95), 2)
        average_temperature = round(rng.uniform(20, 45), 2)
        anomaly_reason = None

        anomaly_type = anomaly_types.get(index)
        if anomaly_type == 0:
            battery_end = round(rng.uniform(1, 19), 2)
            anomaly_reason = "低电量：battery_end < 20"
        elif anomaly_type == 1:
            average_temperature = round(rng.uniform(46, 65), 2)
            anomaly_reason = "高温：average_temperature > 45"
        elif anomaly_type == 2:
            max_speed = round(rng.uniform(31, 45), 2)
            anomaly_reason = "高速：max_speed > 30"

        battery_start = round(rng.uniform(max(60, battery_end + 1), 100), 2)
        records.append({
            # 固定模拟任务编号，重复初始化时通过 UNIQUE 约束跳过已存在记录。
            "flight_id": f"SIM-FLIGHT-{index + 1:04d}",
            "drone_id": f"UAV-{rng.randint(1, 10):03d}",
            "start_time": start_time,
            "end_time": start_time + timedelta(seconds=duration_seconds),
            "duration_seconds": duration_seconds,
            "average_height": average_height,
            "max_height": max_height,
            "average_speed": average_speed,
            "max_speed": max_speed,
            "battery_start": battery_start,
            "battery_end": battery_end,
            "average_temperature": average_temperature,
            "anomaly_status": "warning" if anomaly_reason else "normal",
            "anomaly_reason": anomaly_reason,
        })

    return records


def init_flight_records() -> int:
    """只在 uav_project 建 flight_records 表，返回实际新增的模拟记录数。"""
    records = generate_mock_flights()
    with get_connection() as conn:
        # 使用原连接配置；配置指向其他库时拒绝写入，不自动创建或切换数据库。
        if conn.info.dbname != "uav_project":
            raise ValueError("初始化只允许连接已有数据库 uav_project")

        with conn.cursor() as cursor:
            cursor.execute(CREATE_TABLE_SQL)
            cursor.executemany(INSERT_FLIGHT_SQL, records)
            inserted = cursor.rowcount

    # 连接上下文正常退出时提交，建表或插入失败时整笔事务回滚。
    return inserted


if __name__ == "__main__":
    try:
        inserted_count = init_flight_records()
    except (psycopg.Error, ValueError) as exc:
        print(f"Initialization failed: {exc}", file=sys.stderr)
        sys.exit(1)
    print(
        f"flight_records initialized in uav_project: {inserted_count} records inserted. "
        "Existing simulated flight_id values were skipped."
    )
