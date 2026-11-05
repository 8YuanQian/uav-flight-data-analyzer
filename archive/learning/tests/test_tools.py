"""飞行记录工具返回当前表中的编号和汇总。"""

import psycopg

from src.agent.tools import get_latest_flight_analysis as tool


def test_latest_flight_not_found(monkeypatch):
    monkeypatch.setattr(tool, "get_latest_flight", lambda: None)
    assert tool.get_latest_flight_analysis() == {
        "status": "not_found", "analysis": None
    }


def test_latest_flight_returns_current_record(monkeypatch):
    monkeypatch.setattr(tool, "get_latest_flight", lambda: {
        "id": 17, "uav_code": "UAV-01", "filename": "flight.csv",
        "row_count": 2, "max_speed": 10, "max_temperature": 27,
        "minimum_battery": 80,
    })

    result = tool.get_latest_flight_analysis()

    assert result["status"] == "ok"
    assert result["analysis"]["record_id"] == 17
    assert result["analysis"]["uav_code"] == "UAV-01"
    assert result["analysis"]["summary"]["row_count"] == 2


def test_latest_flight_database_error(monkeypatch):
    def fail():
        raise psycopg.OperationalError("offline")
    monkeypatch.setattr(tool, "get_latest_flight", fail)

    result = tool.get_latest_flight_analysis()

    assert result["status"] == "error"
    assert result["error"]["code"] == "DATABASE_ERROR"
