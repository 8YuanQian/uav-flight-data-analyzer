"""测试使用替身连接和缓存，不自动修改任何数据库数据。"""

import pytest
from src.auth.data_scope import use_data_user


@pytest.fixture(autouse=True)
def data_user():
    # 直接调用业务函数的单元测试明确使用用户 1；HTTP 仍必须独立通过 JWT。
    with use_data_user(1):
        yield


@pytest.fixture
def flight_group():
    # CSV 的 flight_id 与数据库生成的记录 ID 分别保存。
    return {
        "uav_code": "UAV-01",
        "uav_model": "Test Model",
        "manufacturer": "Test Maker",
        "csv_flight_id": "CSV-01",
        "start_time": "2026-01-01 10:00",
        "end_time": "2026-01-01 10:30",
        "duration_minutes": 30,
        "row_count": 2,
        "average_height": 20.0,
        "max_height": 25.0,
        "average_speed": 8.0,
        "max_speed": 10.0,
        "battery_start": 90.0,
        "battery_end": 80.0,
        "minimum_battery": 80.0,
        "average_temperature": 25.0,
        "max_temperature": 27.0,
        "anomaly_status": "normal",
        "anomaly_reason": None,
    }
