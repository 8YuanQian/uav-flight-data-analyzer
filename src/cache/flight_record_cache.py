"""Cache-aside access for UAV-linked flight records."""

from urllib.parse import quote

from redis.exceptions import RedisError

from src.database.flight_record_repository import get_flight_by_id, get_recent_flights

from .flight_analysis_cache import CacheWriteError, _read_through


DETAIL_TTL_SECONDS = 300
LIST_TTL_SECONDS = 60
UNFILTERED_LIST_KEYS = tuple(
    f"uav:flight_records:list:v1:all:{limit}" for limit in range(1, 101)
)


def _list_key(limit: int, uav_code: str | None) -> str:
    if uav_code is None:
        return UNFILTERED_LIST_KEYS[limit - 1]
    return f"uav:flight_records:list:v1:{quote(uav_code, safe='')}:{limit}"


def get_cached_flight_record(cache, record_id: int):
    return _read_through(
        cache,
        f"uav:flight_records:by_id:v1:{record_id}",
        DETAIL_TTL_SECONDS,
        lambda: get_flight_by_id(record_id),
    )


def get_cached_flight_records(cache, limit: int, uav_code: str | None = None):
    return _read_through(
        cache,
        _list_key(limit, uav_code),
        LIST_TTL_SECONDS,
        lambda: get_recent_flights(limit, uav_code),
    )


def invalidate_flight_record_lists(cache, uav_codes=()):
    keys = list(UNFILTERED_LIST_KEYS)
    for code in set(uav_codes):
        keys.extend(_list_key(limit, code) for limit in range(1, 101))
    try:
        cache.delete(*keys)
    except RedisError as exc:
        raise CacheWriteError("Flight record list cache invalidation failed") from exc


def invalidate_flight_record_after_update(cache, record_id: int, uav_code: str):
    keys = [f"uav:flight_records:by_id:v1:{record_id}"]
    keys.extend(UNFILTERED_LIST_KEYS)
    keys.extend(_list_key(limit, uav_code) for limit in range(1, 101))
    try:
        cache.delete(*keys)
    except RedisError as exc:
        raise CacheWriteError("Flight record cache invalidation failed") from exc
