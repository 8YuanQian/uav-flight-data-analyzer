"""无人机历史飞行记录查询，复用项目已有的 PostgreSQL 连接。"""

from typing import Any

from psycopg.rows import dict_row

from src.database import get_connection


def get_latest_flight() -> dict[str, Any] | None:
    """按飞行开始时间获取最新记录；没有记录时返回 None。"""
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            # 开始时间为空的记录排在最后，同一时间用 id 保证顺序稳定。
            cursor.execute(
                "SELECT * FROM flight_records "
                "ORDER BY start_time DESC NULLS LAST, id DESC LIMIT 1"
            )
            return cursor.fetchone()


def get_flight_by_id(flight_id: str) -> dict[str, Any] | None:
    """根据飞行任务编号查询；不存在时返回 None。"""
    if not isinstance(flight_id, str) or not flight_id.strip():
        raise ValueError("flight_id 必须是非空字符串")

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM flight_records WHERE flight_id = %s",
                (flight_id,),
            )
            return cursor.fetchone()


def get_recent_flights(limit: int) -> list[dict[str, Any]]:
    """按飞行开始时间获取最近 limit 条记录；没有记录时返回空列表。"""
    if type(limit) is not int or limit <= 0:
        raise ValueError("limit 必须是正整数")

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM flight_records "
                "ORDER BY start_time DESC NULLS LAST, id DESC LIMIT %s",
                (limit,),
            )
            return cursor.fetchall()
