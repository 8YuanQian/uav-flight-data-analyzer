"""Read and write per-flight summaries in the new UAV-linked table."""

from typing import Any, Callable
from uuid import UUID

from psycopg.rows import dict_row

from src.common.uav_code import normalize_uav_code
from src.auth.data_scope import require_data_user_id

from .connection import get_connection
from .uav_repository import get_or_create_uav


RECORD_COLUMNS = (
    "start_time", "end_time", "duration_minutes", "row_count",
    "average_height", "max_height", "average_speed", "max_speed",
    "battery_start", "battery_end", "minimum_battery",
    "average_temperature", "max_temperature", "anomaly_status", "anomaly_reason",
)


class FlightRecordVersionConflict(Exception):
    """The stored record has a newer version than the caller supplied."""


class FlightTaskAlreadyWritten(RuntimeError):
    """同一任务已经写入飞行器或飞行记录。"""


def save_flight_groups(
    filename: str, groups: list[dict], *,
    task_id: UUID | None = None,
    task_guard: Callable[[Any], None] | None = None,
    on_saved: Callable[[Any, list[dict]], None] | None = None,
) -> list[dict]:
    """Commit all UAVs and flights together; no CSV flight_id enters the SQL insert."""
    user_id = require_data_user_id()
    if task_id is not None and (task_guard is None or on_saved is None):
        raise ValueError("带 task_id 的写入必须同时检查租约并提交任务状态")
    saved = []
    with get_connection() as conn:
        with conn.cursor() as cursor:
            # 任务所有权检查与飞行记录写入共用事务，避免失去租约后继续提交。
            if task_guard is not None:
                task_guard(cursor)
            if task_id is not None:
                # 先检查两张业务表；若任务状态异常丢失，也不能重复写入。
                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM uavs WHERE task_id = %s) "
                    "OR EXISTS (SELECT 1 FROM flight_records WHERE task_id = %s)",
                    (task_id, task_id),
                )
                if cursor.fetchone()[0]:
                    raise FlightTaskAlreadyWritten(f"任务 {task_id} 已写入，拒绝重复入库")
            uav_ids = {}
            for group in groups:
                code = normalize_uav_code(group["uav_code"])
                if code not in uav_ids:
                    uav_ids[code] = get_or_create_uav(
                        cursor, code, group["uav_model"], group["manufacturer"], task_id=task_id
                    )
                columns = ("uav_id", "filename", "task_id", "user_id", *RECORD_COLUMNS)
                values = (uav_ids[code], filename, task_id, user_id, *(group[field] for field in RECORD_COLUMNS))
                placeholders = ", ".join(["%s"] * len(columns))
                cursor.execute(
                    f"INSERT INTO flight_records ({', '.join(columns)}) "
                    f"VALUES ({placeholders}) RETURNING id",
                    values,
                )
                saved.append({
                    "id": cursor.fetchone()[0],
                    "uav_id": uav_ids[code],
                    "uav_code": code,
                    "csv_flight_id": group["csv_flight_id"],
                })
            if on_saved is not None:
                on_saved(cursor, saved)
    return saved


def _select_flights(cursor, where: str = "", params: tuple = (), limit: int | None = None):
    user_id = require_data_user_id()
    # task_id 仅用于入库幂等校验，不进入业务查询或模型工具结果。
    public_columns = ("id", "uav_id", "filename", *RECORD_COLUMNS, "version", "created_at")
    query = (
        "SELECT " + ", ".join(f"flight.{column}" for column in public_columns)
        + ", uav.uav_code, uav.uav_model, uav.manufacturer "
        "FROM flight_records AS flight JOIN uavs AS uav ON uav.id = flight.uav_id "
        + "WHERE uav.user_id = %s AND flight.user_id = %s "
        + ("AND " + where.removeprefix("WHERE ") if where else "")
        + " ORDER BY flight.start_time DESC, flight.id DESC"
    )
    params = (user_id, user_id, *params)
    if limit is not None:
        query += " LIMIT %s"
        params += (limit,)
    cursor.execute(query, params)


def get_latest_flight() -> dict[str, Any] | None:
    require_data_user_id()
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            _select_flights(cursor, limit=1)
            return cursor.fetchone()


def get_flight_by_id(record_id: int) -> dict[str, Any] | None:
    """Look up the database-generated numeric id, not the CSV group label."""
    if type(record_id) is not int or record_id <= 0:
        raise ValueError("id 必须是正整数")
    require_data_user_id()
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            _select_flights(cursor, "WHERE flight.id = %s", (record_id,))
            return cursor.fetchone()


def get_recent_flights(limit: int, uav_code: str | None = None, *, uav_id: int | None = None) -> list[dict[str, Any]]:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit 必须在 1 到 100 之间")
    require_data_user_id()
    if uav_id is not None and (type(uav_id) is not int or uav_id <= 0):
        raise ValueError("uav_id 必须是正整数")
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            if uav_id is not None:
                _select_flights(cursor, "WHERE uav.id = %s", (uav_id,), limit)
            elif uav_code is None:
                _select_flights(cursor, limit=limit)
            else:
                _select_flights(cursor, "WHERE uav.uav_code = %s", (normalize_uav_code(uav_code),), limit)
            return cursor.fetchall()


def update_flight_record(record_id: int, expected_version: int, filename: str, values: dict):
    """Atomically replace a summary only when its version still matches."""
    if type(record_id) is not int or record_id <= 0:
        raise ValueError("id 必须是正整数")
    user_id = require_data_user_id()
    assignments = ", ".join(f"{column} = %s" for column in RECORD_COLUMNS)
    parameters = (filename, *(values[column] for column in RECORD_COLUMNS), record_id, expected_version, user_id, user_id)
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"UPDATE flight_records SET filename = %s, {assignments}, "
                "version = version + 1 WHERE id = %s AND version = %s AND user_id = %s "
                "AND EXISTS (SELECT 1 FROM uavs WHERE uavs.id = flight_records.uav_id AND uavs.user_id = %s) RETURNING id",
                parameters,
            )
            if cursor.fetchone() is not None:
                _select_flights(cursor, "WHERE flight.id = %s", (record_id,))
                return cursor.fetchone()
            cursor.execute(
                "SELECT 1 FROM flight_records AS flight JOIN uavs AS uav ON uav.id = flight.uav_id "
                "WHERE flight.id = %s AND flight.user_id = %s AND uav.user_id = %s",
                (record_id, user_id, user_id),
            )
            if cursor.fetchone() is None:
                return None
            raise FlightRecordVersionConflict


def user_owns_flight_records(record_ids):
    user_id = require_data_user_id()
    ids = list(set(record_ids))
    if not ids or any(type(item) is not int or item <= 0 for item in ids):
        return False
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM flight_records AS flight JOIN uavs AS uav ON uav.id = flight.uav_id "
            "WHERE flight.id = ANY(%s) AND flight.user_id = %s AND uav.user_id = %s",
            (ids, user_id, user_id),
        )
        return cursor.fetchone()[0] == len(ids)
