"""新查询模块的单元测试，以及可选的只读 PostgreSQL 集成测试。"""

import os
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from psycopg.rows import dict_row

from scripts import init_flight_records
from src import database
from src.database import flight_repository


@pytest.fixture(autouse=True)
def clean():
    """覆盖父 conftest 的清理 fixture，本模块不删除任何已有表的数据。"""
    yield


@pytest.fixture
def mock_database(monkeypatch):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(flight_repository, "get_connection", lambda: connection)
    return connection, cursor


def test_get_latest_flight(mock_database):
    connection, cursor = mock_database
    record = {"id": 100, "flight_id": "SIM-FLIGHT-0100"}
    cursor.fetchone.return_value = record

    result = flight_repository.get_latest_flight()

    assert result == record
    assert isinstance(result, dict)
    connection.cursor.assert_called_once_with(row_factory=dict_row)


def test_get_flight_by_id(mock_database):
    connection, cursor = mock_database
    record = {"id": 1, "flight_id": "SIM-FLIGHT-0001"}
    cursor.fetchone.return_value = record

    assert flight_repository.get_flight_by_id(record["flight_id"]) == record
    assert cursor.execute.call_args.args[1] == (record["flight_id"],)
    connection.cursor.assert_called_once_with(row_factory=dict_row)


def test_get_recent_flights_limit(mock_database):
    connection, cursor = mock_database
    records = [{"flight_id": "SIM-FLIGHT-0100"}, {"flight_id": "SIM-FLIGHT-0099"}]
    cursor.fetchall.return_value = records

    assert flight_repository.get_recent_flights(2) == records
    assert cursor.execute.call_args.args[1] == (2,)
    connection.cursor.assert_called_once_with(row_factory=dict_row)


def test_nonexistent_flight_id_returns_none(mock_database):
    _, cursor = mock_database
    cursor.fetchone.return_value = None
    assert flight_repository.get_flight_by_id("missing-flight") is None


def test_latest_flight_empty_returns_none(mock_database):
    _, cursor = mock_database
    cursor.fetchone.return_value = None
    assert flight_repository.get_latest_flight() is None


def test_recent_flights_empty_returns_list(mock_database):
    _, cursor = mock_database
    cursor.fetchall.return_value = []
    assert flight_repository.get_recent_flights(5) == []


def test_flight_id_is_passed_as_parameter(mock_database):
    _, cursor = mock_database
    flight_id = "flight'; DROP TABLE documents; --"
    flight_repository.get_flight_by_id(flight_id)
    sql, parameters = cursor.execute.call_args.args
    assert flight_id not in sql
    assert parameters == (flight_id,)


@pytest.mark.parametrize("limit", [0, -1, True, "3", 3.5, None])
def test_invalid_limit_rejected_without_connecting(monkeypatch, limit):
    connect = MagicMock()
    monkeypatch.setattr(flight_repository, "get_connection", connect)
    with pytest.raises(ValueError, match="limit"):
        flight_repository.get_recent_flights(limit)
    connect.assert_not_called()


@pytest.mark.parametrize("flight_id", ["", " ", None, 123])
def test_invalid_flight_id_rejected_without_connecting(monkeypatch, flight_id):
    connect = MagicMock()
    monkeypatch.setattr(flight_repository, "get_connection", connect)
    with pytest.raises(ValueError, match="flight_id"):
        flight_repository.get_flight_by_id(flight_id)
    connect.assert_not_called()


def test_simulated_records_match_required_ranges_and_anomalies():
    records = init_flight_records.generate_mock_flights(seed=42)
    assert len(records) == 100
    assert len({record["flight_id"] for record in records}) == 100
    assert sum(record["anomaly_status"] == "warning" for record in records) == 15
    assert sum(record["battery_end"] < 20 for record in records) == 5
    assert sum(record["average_temperature"] > 45 for record in records) == 5
    assert sum(record["max_speed"] > 30 for record in records) == 5

    for record in records:
        assert 50 <= record["average_height"] <= record["max_height"] <= 150
        assert 5 <= record["average_speed"] <= record["max_speed"]
        assert 0 <= record["battery_end"] <= record["battery_start"] <= 100
        assert record["start_time"].utcoffset() is not None
        assert (record["end_time"] - record["start_time"]).total_seconds() == record["duration_seconds"]
        if record["anomaly_status"] == "normal":
            assert 5 <= record["max_speed"] <= 25
            assert 20 <= record["average_temperature"] <= 45
            assert 20 <= record["battery_end"] <= 100
            assert record["anomaly_reason"] is None
        else:
            assert record["anomaly_reason"]


def test_init_refuses_another_database_before_writing(monkeypatch):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.info.dbname = "uav_project_test"
    monkeypatch.setattr(init_flight_records, "get_connection", lambda: connection)
    with pytest.raises(ValueError, match="uav_project"):
        init_flight_records.init_flight_records()
    connection.cursor.assert_not_called()


def test_legacy_database_interface_is_preserved(monkeypatch):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [{"id": 7}]
    monkeypatch.setattr(database, "get_connection", lambda: connection)
    # 包与原模块共享命名空间，已有分析记录函数仍使用同一个连接入口。
    assert database.get_flight_records(1) == [{"id": 7}]
    assert callable(database.save_flight_analysis)
    assert callable(database.get_flight_analysis)


@pytest.fixture
def live_repository(monkeypatch):
    # 父 conftest 会设置测试库名；此处仅在当前测试中恢复业务库目标。
    # 所有实际连接设为只读，不创建测试库，不写入或清理数据。
    monkeypatch.setattr(database, "DB_NAME", "uav_project")

    def read_only_connection():
        connection = database.get_connection()
        if connection.info.dbname != "uav_project":
            connection.close()
            raise RuntimeError("Expected existing uav_project database")
        connection.read_only = True
        return connection

    monkeypatch.setattr(flight_repository, "get_connection", read_only_connection)
    return flight_repository


live_test = pytest.mark.skipif(
    os.getenv("UAV_FLIGHT_INTEGRATION") != "1",
    reason="Set UAV_FLIGHT_INTEGRATION=1 after initializing flight_records",
)


@live_test
def test_live_latest_flight(live_repository):
    latest = live_repository.get_latest_flight()
    assert isinstance(latest, dict)
    assert latest == live_repository.get_recent_flights(1)[0]


@live_test
def test_live_flight_by_id(live_repository):
    record = live_repository.get_flight_by_id("SIM-FLIGHT-0001")
    assert isinstance(record, dict)
    assert record["flight_id"] == "SIM-FLIGHT-0001"


@live_test
def test_live_recent_flights_limit(live_repository):
    records = live_repository.get_recent_flights(5)
    assert len(records) == 5
    assert all(isinstance(record, dict) for record in records)
    ordering = [(record["start_time"], record["id"]) for record in records]
    assert ordering == sorted(ordering, reverse=True)


@live_test
def test_live_missing_flight_id_returns_none(live_repository):
    assert live_repository.get_flight_by_id(f"missing-{uuid4()}") is None
