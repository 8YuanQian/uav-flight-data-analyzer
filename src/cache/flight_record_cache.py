"""Cache-aside access for UAV-linked flight records."""

from urllib.parse import quote

from redis.exceptions import RedisError

from src.common.uav_code import normalize_uav_code
from src.auth.data_scope import require_data_user_id
from src.database.flight_record_repository import get_flight_by_id, get_recent_flights

from .cache_aside import CacheWriteError, _read_through


DETAIL_TTL_SECONDS = 300
LIST_TTL_SECONDS = 60


def _list_key(limit: int, uav_code: str | None, uav_id: int | None = None) -> str:
    prefix = f"uav:users:{require_data_user_id()}:flight_records:list:v2"
    if uav_id is not None:
        return f"{prefix}:uav-id:{uav_id}:{limit}"
    if uav_code is None:
        return f"{prefix}:all:{limit}"
    return f"{prefix}:code:{quote(normalize_uav_code(uav_code), safe='')}:{limit}"


def get_cached_flight_record(cache, record_id: int):
    return _read_through(
        cache,
        f"uav:users:{require_data_user_id()}:flight_records:by_id:v2:{record_id}",
        DETAIL_TTL_SECONDS,
        lambda: get_flight_by_id(record_id),
    )


def get_cached_flight_records(cache, limit: int, uav_code: str | None = None, *, uav_id: int | None = None):
    return _read_through(
        cache,
        _list_key(limit, uav_code, uav_id),
        LIST_TTL_SECONDS,
        lambda: get_recent_flights(limit, uav_code, uav_id=uav_id) if uav_id is not None else get_recent_flights(limit, uav_code),
    )


def invalidate_flight_record_lists(cache, uav_codes=(), *, uav_ids=()):
    keys = [_list_key(limit, None) for limit in range(1, 101)]
    for code in set(uav_codes):
        keys.extend(_list_key(limit, code) for limit in range(1, 101))
    for uav_id in set(uav_ids):
        keys.extend(_list_key(limit, None, uav_id) for limit in range(1, 101))
    try:
        cache.delete(*keys)
    except RedisError as exc:
        raise CacheWriteError("Flight record list cache invalidation failed") from exc


def invalidate_flight_record_after_update(cache, record_id: int, uav_code: str, uav_id: int):
    keys = [f"uav:users:{require_data_user_id()}:flight_records:by_id:v2:{record_id}"]
    keys.extend(_list_key(limit, None) for limit in range(1, 101))
    keys.extend(_list_key(limit, uav_code) for limit in range(1, 101))
    keys.extend(_list_key(limit, None, uav_id) for limit in range(1, 101))
    try:
        cache.delete(*keys)
    except RedisError as exc:
        raise CacheWriteError("Flight record cache invalidation failed") from exc
