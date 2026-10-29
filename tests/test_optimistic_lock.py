"""飞行分析记录的版本冲突、接口状态和缓存失效。"""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from app.flight_data_router import flight_router
from src.cache.flight_analysis_cache import LIST_KEYS
from src.database import flight_analysis_repository as repository


@pytest.fixture(autouse=True)
def clean():
    """本模块使用假连接，不触碰全局 conftest 的测试数据库。"""
    yield


UPDATE_BODY = {
    "version": 3,
    "filename": "revised.csv",
    "row_count": 10,
    "average_height": 50.0,
    "average_speed": 12.0,
    "average_temperature": 26.0,
    "max_height": 70.0,
    "max_speed": 18.0,
    "max_temperature": 30.0,
    "minimum_battery": 40.0,
}


def fake_repository_connection(monkeypatch, results):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = results
    monkeypatch.setattr(repository, "get_connection", lambda: connection)
    return cursor


def test_update_checks_version_in_same_sql_statement(monkeypatch):
    updated = {"id": 17, "version": 4, "filename": "revised.csv"}
    cursor = fake_repository_connection(monkeypatch, [updated])

    result = repository.update_flight_analysis(17, 3, "revised.csv", UPDATE_BODY)

    assert result == updated
    cursor.execute.assert_called_once()
    sql, values = cursor.execute.call_args.args
    assert "UPDATE flight_analyses" in sql
    assert "version = version + 1" in sql
    assert "WHERE id = %s AND version = %s" in sql
    assert "RETURNING *" in sql
    assert values[-2:] == (17, 3)


def test_stale_version_reports_conflict_without_overwriting(monkeypatch):
    cursor = fake_repository_connection(monkeypatch, [None, (1,)])

    with pytest.raises(repository.FlightAnalysisVersionConflict):
        repository.update_flight_analysis(17, 3, "revised.csv", UPDATE_BODY)

    assert cursor.execute.call_count == 2
    assert "SELECT 1" in cursor.execute.call_args.args[0]


def test_missing_analysis_is_distinct_from_conflict(monkeypatch):
    fake_repository_connection(monkeypatch, [None, None])

    assert repository.update_flight_analysis(999, 1, "revised.csv", UPDATE_BODY) is None


def make_app(monkeypatch, update_result):
    import app.flight_data_router as router_module

    app = FastAPI()
    app.state.db_pool = object()
    cache = MagicMock()
    app.state.cache = cache

    if isinstance(update_result, Exception):
        def update(*args):
            raise update_result
    else:
        def update(*args):
            return update_result

    monkeypatch.setattr(router_module, "update_flight_analysis", update)
    app.include_router(flight_router)
    return TestClient(app), cache


def test_update_route_clears_detail_and_list_cache(monkeypatch):
    client, cache = make_app(monkeypatch, {"id": 17, "version": 4})

    response = client.put("/flight/flights/17", json=UPDATE_BODY)

    assert response.status_code == 200
    assert response.json()["version"] == 4
    assert cache.delete.call_count == 1
    assert cache.delete.call_args.args == (
        "uav:flight_analyses:by_id:v1:17", *LIST_KEYS
    )


def test_update_route_rejects_stale_version_without_cache_change(monkeypatch):
    client, cache = make_app(monkeypatch, repository.FlightAnalysisVersionConflict())

    response = client.put("/flight/flights/17", json=UPDATE_BODY)

    assert response.status_code == 409
    cache.delete.assert_not_called()


def test_update_route_reports_missing_record(monkeypatch):
    client, cache = make_app(monkeypatch, None)

    response = client.put("/flight/flights/999", json=UPDATE_BODY)

    assert response.status_code == 404
    cache.delete.assert_not_called()


def test_update_route_reports_committed_version_when_cache_fails(monkeypatch):
    client, cache = make_app(monkeypatch, {"id": 17, "version": 4})
    cache.delete.side_effect = RedisConnectionError("cache unavailable")

    response = client.put("/flight/flights/17", json=UPDATE_BODY)

    assert response.status_code == 503
    assert response.json()["detail"]["analysis_id"] == 17
    assert response.json()["detail"]["version"] == 4
