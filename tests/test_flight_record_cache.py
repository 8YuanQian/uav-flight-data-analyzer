"""当前飞行记录缓存的命中、回源、失败和失效测试。"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from src.cache import flight_record_cache as cache_module


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
        return len(keys)


def test_record_cache_miss_then_hit(monkeypatch):
    cache = FakeCache()
    calls = []
    row = {
        "id": 17, "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "duration_minutes": Decimal("30.00"),
    }
    monkeypatch.setattr(
        cache_module, "get_flight_by_id",
        lambda record_id: calls.append(record_id) or row,
    )

    assert cache_module.get_cached_flight_record(cache, 17) is row
    second = cache_module.get_cached_flight_record(cache, 17)

    assert second["duration_minutes"] == 30
    assert second["created_at"] == "2026-01-01T00:00:00+00:00"
    assert calls == [17]


def test_cache_read_failure_queries_database(monkeypatch):
    cache = FakeCache()
    cache.fail_get = True
    monkeypatch.setattr(cache_module, "get_flight_by_id", lambda record_id: {"id": record_id})

    assert cache_module.get_cached_flight_record(cache, 17) == {"id": 17}
    assert "uav:users:1:flight_records:by_id:v2:17" in cache.values


def test_cache_write_failure_is_reported(monkeypatch):
    cache = FakeCache()
    cache.fail_set = True
    monkeypatch.setattr(cache_module, "get_flight_by_id", lambda record_id: {"id": record_id})

    with pytest.raises(cache_module.CacheWriteError):
        cache_module.get_cached_flight_record(cache, 17)


def test_list_cache_separates_limit_and_uav_code(monkeypatch):
    cache = FakeCache()
    calls = []
    monkeypatch.setattr(
        cache_module, "get_recent_flights",
        lambda limit, uav_code: calls.append((limit, uav_code)) or [{"id": limit}],
    )

    cache_module.get_cached_flight_records(cache, 1, "uav-01")
    cache_module.get_cached_flight_records(cache, 1, "UAV-01")
    cache_module.get_cached_flight_records(cache, 2, "UAV-01")

    assert calls == [(1, "uav-01"), (2, "UAV-01")]


def test_update_invalidates_detail_and_lists():
    cache = FakeCache()
    cache.values = {
        "uav:users:1:flight_records:by_id:v2:17": "old",
        "uav:users:1:flight_records:list:v2:all:1": "old",
        "uav:users:1:flight_records:list:v2:code:UAV-01:1": "old",
    }

    cache_module.invalidate_flight_record_after_update(cache, 17, "uav-01", 3)

    assert cache.values == {}


def test_cache_invalidation_failure_is_reported():
    cache = FakeCache()
    cache.fail_delete = True
    with pytest.raises(cache_module.CacheWriteError):
        cache_module.invalidate_flight_record_lists(cache, ["UAV-01"])
