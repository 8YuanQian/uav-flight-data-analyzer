"""新飞行记录的原子版本更新和接口错误处理。"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app import flight_data_router as router
from src.database import flight_record_repository as repository
from src.schemas import FlightRecordUpdate


@pytest.fixture
def update_body():
    return {
        "version": 3, "filename": "revised.csv",
        "start_time": datetime(2026, 1, 1, 10, tzinfo=timezone.utc),
        "end_time": datetime(2026, 1, 1, 10, 30, tzinfo=timezone.utc),
        "row_count": 2, "average_height": 20, "max_height": 25,
        "average_speed": 8, "max_speed": 10,
        "battery_start": 90, "battery_end": 80, "minimum_battery": 80,
        "average_temperature": 25, "max_temperature": 27,
        "anomaly_status": "normal", "anomaly_reason": None,
    }


def fake_repository_connection(monkeypatch, results):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = results
    monkeypatch.setattr(repository, "get_connection", lambda: connection)
    return cursor


def test_update_checks_version_in_same_sql_statement(monkeypatch, update_body):
    cursor = fake_repository_connection(
        monkeypatch, [(17,), {"id": 17, "version": 4}]
    )
    values = {key: value for key, value in update_body.items()
              if key not in ("version", "filename")}
    values["duration_minutes"] = 30

    result = repository.update_flight_record(17, 3, "revised.csv", values)

    assert result == {"id": 17, "version": 4}
    sql, parameters = cursor.execute.call_args_list[0].args
    assert "UPDATE flight_records" in sql
    assert "version = version + 1 WHERE id = %s AND version = %s" in sql
    assert parameters[-4:] == (17, 3, 1, 1)


def test_stale_version_does_not_overwrite(monkeypatch, update_body):
    cursor = fake_repository_connection(monkeypatch, [None, (1,)])
    values = {key: value for key, value in update_body.items()
              if key not in ("version", "filename")}
    values["duration_minutes"] = 30

    with pytest.raises(repository.FlightRecordVersionConflict):
        repository.update_flight_record(17, 3, "revised.csv", values)
    assert cursor.execute.call_count == 2


def test_missing_record_is_not_version_conflict(monkeypatch, update_body):
    fake_repository_connection(monkeypatch, [None, None])
    values = {key: value for key, value in update_body.items()
              if key not in ("version", "filename")}
    values["duration_minutes"] = 30
    assert repository.update_flight_record(
        999, 3, "revised.csv", values
    ) is None


def request_with_cache():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(cache=object())))


def test_update_route_calculates_minutes_and_invalidates_cache(monkeypatch, update_body):
    calls = []
    monkeypatch.setattr(
        router, "update_flight_record",
        lambda *args: calls.append(args) or {"id": 17, "version": 4, "uav_code": "UAV-01", "uav_id": 3},
    )
    monkeypatch.setattr(
        router, "invalidate_flight_record_after_update",
        lambda *args: calls.append(args),
    )
    request = request_with_cache()

    result = router.replace_flight_record(
        17, FlightRecordUpdate(**update_body), request
    )

    assert result["version"] == 4
    assert calls[0][3]["duration_minutes"] == 30
    assert calls[1] == (request.app.state.cache, 17, "UAV-01", 3)


@pytest.mark.parametrize("outcome, status", [
    (repository.FlightRecordVersionConflict(), 409), (None, 404),
])
def test_update_route_reports_conflict_or_missing(monkeypatch, update_body, outcome, status):
    def update(*args):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    monkeypatch.setattr(router, "update_flight_record", update)

    with pytest.raises(HTTPException) as error:
        router.replace_flight_record(
            17, FlightRecordUpdate(**update_body), request_with_cache()
        )
    assert error.value.status_code == status


def test_update_route_reports_committed_version_on_cache_failure(monkeypatch, update_body):
    monkeypatch.setattr(
        router, "update_flight_record",
        lambda *args: {"id": 17, "version": 4, "uav_code": "UAV-01", "uav_id": 3},
    )
    def fail(*args):
        raise router.CacheWriteError()
    monkeypatch.setattr(router, "invalidate_flight_record_after_update", fail)

    with pytest.raises(HTTPException) as error:
        router.replace_flight_record(
            17, FlightRecordUpdate(**update_body), request_with_cache()
        )
    assert error.value.status_code == 503
    assert error.value.detail["record_id"] == 17
    assert error.value.detail["version"] == 4
