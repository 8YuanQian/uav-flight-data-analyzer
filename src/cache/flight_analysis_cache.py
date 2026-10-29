"""供 FastAPI 读取 flight_analyses 时使用的 cache-aside 缓存层。"""

import json
import logging

from fastapi.encoders import jsonable_encoder
from redis.exceptions import RedisError

from src.database import get_flight_analysis, get_flight_records


logger = logging.getLogger(__name__)

# 单条记录和列表分别设置过期时间；过期后由下一次请求重新从数据库加载。
DETAIL_TTL_SECONDS = 300
LIST_TTL_SECONDS = 60
# 列表接口的 limit 被限制在 1～100，因此写入新分析后可以一次删除所有列表键。
LIST_KEYS = tuple(
    f"uav:flight_analyses:list:v1:limit:{limit}" for limit in range(1, 101)
)


class CacheWriteError(RuntimeError):
    """数据库操作已成功，但缓存写入或清除失败。"""


def _read_through(cache, key, ttl_seconds, load_from_database):
    """先读 Redis，未命中时查库，并把查到的结果写回 Redis。"""
    try:
        cached = cache.get(key)
    except RedisError:
        # 读缓存失败按缓存未命中处理；查库后的写缓存仍必须成功。
        logger.warning("Cache read failed for %s; querying database", key, exc_info=True)
    else:
        if cached is not None:
            try:
                return json.loads(cached)
            except (TypeError, ValueError):
                # 缓存内容无法解析时重新查库，后续 SET 会覆盖无效内容。
                logger.warning("Invalid cached JSON for %s; querying database", key)

    data = load_from_database()
    if data is None:
        # 不缓存不存在的 ID，避免后续新增记录仍被旧的 404 结果挡住。
        return None

    try:
        # 数据库行可能包含 datetime、Decimal；先转成与接口响应兼容的 JSON 数据。
        encoded = json.dumps(jsonable_encoder(data), ensure_ascii=False)
        if not cache.set(key, encoded, ex=ttl_seconds):
            raise CacheWriteError(f"Cache SET did not succeed for {key}")
    except Exception as exc:
        # 按当前约定，查库成功但写缓存失败时不返回数据库结果。
        logger.error("Cache write failed for %s", key, exc_info=True)
        raise CacheWriteError("Cache write failed") from exc
    return data


def get_cached_flight_analysis(cache, analysis_id):
    # v1 用于区分以后可能调整的缓存数据格式。
    key = f"uav:flight_analyses:by_id:v1:{analysis_id}"
    return _read_through(
        cache, key, DETAIL_TTL_SECONDS, lambda: get_flight_analysis(analysis_id)
    )


def get_cached_flight_records(cache, limit):
    # 不同 limit 必须使用不同的键，否则列表条数可能串用。
    key = LIST_KEYS[limit - 1]
    return _read_through(cache, key, LIST_TTL_SECONDS, lambda: get_flight_records(limit))


def invalidate_flight_analysis_lists(cache):
    """新增分析记录后，清除所有允许的 limit 对应的列表缓存。"""
    try:
        # 新增记录会改变按创建时间排序的列表；按 ID 的缓存无需删除。
        cache.delete(*LIST_KEYS)
    except RedisError as exc:
        logger.error("Flight analysis list cache invalidation failed", exc_info=True)
        raise CacheWriteError("Cache invalidation failed") from exc


def invalidate_flight_analysis_after_update(cache, analysis_id):
    """更新已有记录后，同时删除按 ID 的缓存和全部列表缓存。"""
    detail_key = f"uav:flight_analyses:by_id:v1:{analysis_id}"
    try:
        cache.delete(detail_key, *LIST_KEYS)
    except RedisError as exc:
        logger.error("Flight analysis cache invalidation failed", exc_info=True)
        raise CacheWriteError("Cache invalidation failed") from exc
