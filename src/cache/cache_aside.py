# 通用缓存读取逻辑，由当前业务缓存复用，不依赖任何具体数据库表。
import json
import logging

from fastapi.encoders import jsonable_encoder
from redis.exceptions import RedisError


logger = logging.getLogger(__name__)


class CacheWriteError(RuntimeError):
    # 数据库操作已成功，但缓存写入或清除失败。
    pass


def _read_through(cache, key, ttl_seconds, load_from_database):
    # 缓存未命中或读取失败时查询数据库；写回失败必须向调用方报错。
    try:
        cached = cache.get(key)
    except RedisError:
        logger.warning("Cache read failed for %s; querying database", key, exc_info=True)
    else:
        if cached is not None:
            try:
                return json.loads(cached)
            except (TypeError, ValueError):
                # 无效缓存按未命中处理，后续写回会覆盖原内容。
                logger.warning("Invalid cached JSON for %s; querying database", key)

    data = load_from_database()
    if data is None:
        # 不缓存不存在的记录。
        return None

    try:
        # 将日期和 Decimal 转成接口可以返回的 JSON 数据。
        encoded = json.dumps(jsonable_encoder(data), ensure_ascii=False)
        if not cache.set(key, encoded, ex=ttl_seconds):
            raise CacheWriteError(f"Cache SET did not succeed for {key}")
    except Exception as exc:
        logger.error("Cache write failed for %s", key, exc_info=True)
        raise CacheWriteError("Cache write failed") from exc
    return data
