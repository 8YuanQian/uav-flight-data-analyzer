"""飞行记录仓库使用新表、系统 ID 和飞行器编号。"""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from psycopg.rows import dict_row

from src.database import flight_record_repository as repository


@pytest.fixture
def mock_database(monkeypatch):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(repository, "get_connection", lambda: connection)
    return connection, cursor


def test_get_latest_flight(mock_database):
    connection, cursor = mock_database
    row = {"id": 17, "uav_code": "UAV-01"}
    cursor.fetchone.return_value = row

    assert repository.get_latest_flight() == row
    sql, parameters = cursor.execute.call_args.args
    assert "FROM flight_records AS flight JOIN uavs AS uav" in sql
    assert parameters == (1, 1, 1)
    connection.cursor.assert_called_once_with(row_factory=dict_row)


def test_get_flight_by_system_id(mock_database):
    _, cursor = mock_database
    cursor.fetchone.return_value = {"id": 17}

    assert repository.get_flight_by_id(17) == {"id": 17}
    sql, parameters = cursor.execute.call_args.args
    assert "AND flight.id = %s" in sql
    assert parameters == (1, 1, 17)
    assert "csv_flight_id" not in sql


def test_get_recent_flights_by_uav_code(mock_database):
    _, cursor = mock_database
    cursor.fetchall.return_value = [{"id": 17}]

    assert repository.get_recent_flights(2, "uav-01") == [{"id": 17}]
    sql, parameters = cursor.execute.call_args.args
    assert "AND uav.uav_code = %s" in sql
    assert parameters == (1, 1, "UAV-01", 2)


@pytest.mark.parametrize("record_id", [0, -1, True, "17", None])
def test_invalid_record_id_rejected_without_connection(monkeypatch, record_id):
    connect = MagicMock()
    monkeypatch.setattr(repository, "get_connection", connect)
    with pytest.raises(ValueError, match="id"):
        repository.get_flight_by_id(record_id)
    connect.assert_not_called()


@pytest.mark.parametrize("limit", [0, 101, True, "3", None])
def test_invalid_limit_rejected_without_connection(monkeypatch, limit):
    connect = MagicMock()
    monkeypatch.setattr(repository, "get_connection", connect)
    with pytest.raises(ValueError, match="limit"):
        repository.get_recent_flights(limit)
    connect.assert_not_called()


def test_save_groups_keeps_csv_flight_id_out_of_insert(monkeypatch, mock_database, flight_group):
    _, cursor = mock_database
    cursor.fetchone.return_value = (17,)
    monkeypatch.setattr(repository, "get_or_create_uav", lambda *args, **kwargs: 3)

    saved = repository.save_flight_groups("flight.csv", [flight_group])

    assert saved == [{
        "id": 17, "uav_id": 3, "uav_code": "UAV-01",
        "csv_flight_id": "CSV-01",
    }]
    sql, parameters = cursor.execute.call_args.args
    assert "INSERT INTO flight_records" in sql
    assert "csv_flight_id" not in sql
    assert "CSV-01" not in parameters


def test_task_id_requires_guard_and_final_state(mock_database, flight_group):
    with pytest.raises(ValueError, match="task_id"):
        repository.save_flight_groups(
            "flight.csv", [flight_group], task_id=uuid4()
        )


def test_duplicate_task_does_not_write_again(mock_database, flight_group):
    _, cursor = mock_database
    cursor.fetchone.return_value = (True,)
    task_id = uuid4()

    with pytest.raises(repository.FlightTaskAlreadyWritten):
        repository.save_flight_groups(
            "flight.csv", [flight_group], task_id=task_id,
            task_guard=lambda cursor: None,
            on_saved=lambda cursor, rows: None,
        )

    sql, params = cursor.execute.call_args.args
    assert "uavs WHERE task_id = %s" in sql
    assert "flight_records WHERE task_id = %s" in sql
    assert params == (task_id, task_id)
