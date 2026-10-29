from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

import src.cache.flight_analysis_cache as flight_cache


@pytest.fixture(autouse=True)
def clean():
    """缓存测试已替换数据库调用，不需要连接测试数据库。"""
    yield


class FakeCache:
    def __init__(self):
        self.values = {}
        self.fail_get = False
        self.fail_set = False
        self.fail_delete = False

    def get(self, key):
        if self.fail_get:
            raise RedisConnectionError("cache unavailable")
        return self.values.get(key)

    def set(self, key, value, ex):
        if self.fail_set:
            raise RedisConnectionError("cache unavailable")
        self.values[key] = value
        return True

    def delete(self, *keys):
        if self.fail_delete:
            raise RedisConnectionError("cache unavailable")
        for key in keys:
            self.values.pop(key, None)
        return 1


def test_detail_miss_populates_cache_then_hit_skips_database(monkeypatch):
    cache = FakeCache()
    calls = []
    row = {
        "id": 17,
        "created_at": datetime(2026, 10, 27, tzinfo=timezone.utc),
        "average_speed": Decimal("12.5"),
    }

    def load(analysis_id):
        calls.append(analysis_id)
        return row

    monkeypatch.setattr(flight_cache, "get_flight_analysis", load)

    first = flight_cache.get_cached_flight_analysis(cache, 17)
    second = flight_cache.get_cached_flight_analysis(cache, 17)

    assert first is row
    assert second["id"] == 17
    assert second["created_at"] == "2026-10-27T00:00:00+00:00"
    assert second["average_speed"] == 12.5
    assert calls == [17]


def test_redis_read_error_falls_back_to_database(monkeypatch):
    cache = FakeCache()
    cache.fail_get = True
    monkeypatch.setattr(flight_cache, "get_flight_analysis", lambda analysis_id: {"id": analysis_id})

    assert flight_cache.get_cached_flight_analysis(cache, 17) == {"id": 17}
    assert "uav:flight_analyses:by_id:v1:17" in cache.values


def test_redis_write_error_is_reported_after_database_read(monkeypatch):
    cache = FakeCache()
    cache.fail_get = True
    cache.fail_set = True
    calls = []

    def load(analysis_id):
        calls.append(analysis_id)
        return {"id": analysis_id}

    monkeypatch.setattr(flight_cache, "get_flight_analysis", load)

    with pytest.raises(flight_cache.CacheWriteError):
        flight_cache.get_cached_flight_analysis(cache, 17)
    assert calls == [17]


def test_lists_are_keyed_by_limit_and_cleared_after_insert(monkeypatch):
    cache = FakeCache()
    calls = []

    def load(limit):
        calls.append(limit)
        return [{"id": limit}]

    monkeypatch.setattr(flight_cache, "get_flight_records", load)

    assert flight_cache.get_cached_flight_records(cache, 1) == [{"id": 1}]
    assert flight_cache.get_cached_flight_records(cache, 2) == [{"id": 2}]
    assert flight_cache.get_cached_flight_records(cache, 1) == [{"id": 1}]
    assert calls == [1, 2]

    flight_cache.invalidate_flight_analysis_lists(cache)
    assert flight_cache.get_cached_flight_records(cache, 1) == [{"id": 1}]
    assert calls == [1, 2, 1]


def test_read_endpoint_reports_cache_write_failure(monkeypatch):
    from app.flight_data_router import flight_router

    cache = FakeCache()
    cache.fail_set = True
    monkeypatch.setattr(flight_cache, "get_flight_analysis", lambda analysis_id: {"id": analysis_id})
    app = FastAPI()
    app.state.cache = cache
    app.state.db_pool = object()
    app.include_router(flight_router)

    response = TestClient(app).get("/flight/flights/17")

    assert response.status_code == 503
    assert response.json()["detail"] == "缓存写入失败，请稍后重试"


def test_insert_reports_committed_id_if_cache_invalidation_fails(monkeypatch):
    import app.ai_router as ai_router

    cache = FakeCache()
    cache.fail_delete = True
    monkeypatch.setattr(ai_router, "load_csv_data", lambda file: type("Data", (), {
        "columns": ("time", "speed", "height", "battery", "temperature")
    })())
    monkeypatch.setattr(ai_router, "clean_data", lambda data: data)
    monkeypatch.setattr(ai_router, "calculate_summary", lambda data: {"row_count": 1})
    monkeypatch.setattr(ai_router, "save_flight_analysis", lambda filename, summary: 42)
    app = FastAPI()
    app.state.cache = cache
    app.state.db_pool = object()
    app.include_router(ai_router.ai_flight_router)

    response = TestClient(app).post(
        "/ai_flight/flights/report",
        files={"file": ("flight.csv", b"data", "text/csv")},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["analysis_id"] == 42
