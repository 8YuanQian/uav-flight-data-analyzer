# 验证当前 Graph 使用的飞行记录工具；数据库操作使用替身。
from src.agent.tools import get_flight_data as tool


def test_flight_record_not_found(monkeypatch):
    monkeypatch.setattr(tool, "get_flight_by_id", lambda record_id: None)
    assert tool.get_flight_data(record_id=999) == []


def test_flight_tool_returns_requested_record(monkeypatch):
    monkeypatch.setattr(tool, "get_flight_by_id", lambda record_id: {
        "id": 17, "uav_code": "UAV-01", "filename": "flight.csv",
        "row_count": 2, "max_speed": 10, "max_temperature": 27,
        "minimum_battery": 80,
    })

    result = tool.get_flight_data(record_id=17)

    assert len(result) == 1
    assert result[0]["id"] == 17
    assert result[0]["uav_code"] == "UAV-01"
    assert result[0]["row_count"] == 2


def test_recent_flights_receive_uav_code_and_limit(monkeypatch):
    calls = []
    monkeypatch.setattr(tool, "get_recent_flights", lambda limit, code:
                        calls.append((limit, code)) or [{"id": 17}])

    assert tool.get_flight_data(limit=3, uav_code="UAV-01") == [{"id": 17}]
    assert calls == [(3, "UAV-01")]


def test_recent_flights_receive_system_uav_id(monkeypatch):
    calls = []
    monkeypatch.setattr(tool, "get_recent_flights", lambda limit, code, *, uav_id:
                        calls.append((limit, code, uav_id)) or [])

    assert tool.get_flight_data(limit=2, uav_id=8) == []
    assert calls == [(2, None, 8)]
