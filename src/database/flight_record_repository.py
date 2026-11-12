"""Read and write per-flight summaries in the new UAV-linked table."""

from typing import Any, Callable
from uuid import UUID

from psycopg.errors import UniqueViolation
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


class FlightIdConflict(ValueError):
    """当前用户已经使用该飞行记录编号。"""


def validate_import_flight_ids(flight_ids):
    # 先检查已有编号，避免已知冲突仍调用付费模型；数据库唯一索引处理并发冲突。
    user_id = require_data_user_id()
    ids = list(flight_ids)
    if len(ids) != len(set(ids)):
        raise FlightIdConflict("飞行记录编号在本次文件中重复")
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT flight_id FROM flight_records WHERE user_id = %s AND flight_id = ANY(%s) LIMIT 1",
                (user_id, ids),
            )
            if cursor.fetchone() is not None:
                raise FlightIdConflict("飞行记录编号已存在，请检查 CSV")


def save_flight_groups(
    filename: str, groups: list[dict], *,
    task_id: UUID | None = None,
    task_guard: Callable[[Any], None] | None = None,
    on_saved: Callable[[Any, list[dict]], None] | None = None,
) -> list[dict]:
    """在同一事务中保存飞行器、飞行记录和 CSV 飞行编号。"""
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
                columns = ("uav_id", "filename", "task_id", "user_id", "flight_id", *RECORD_COLUMNS)
                values = (uav_ids[code], filename, task_id, user_id, group["csv_flight_id"], *(group[field] for field in RECORD_COLUMNS))
                placeholders = ", ".join(["%s"] * len(columns))
                try:
                    cursor.execute(
                        f"INSERT INTO flight_records ({', '.join(columns)}) "
                        f"VALUES ({placeholders}) RETURNING id",
                        values,
                    )
                except UniqueViolation as exc:
                    if exc.diag.constraint_name == "flight_records_user_flight_id_key":
                        raise FlightIdConflict("飞行记录编号已存在，请检查 CSV") from exc
                    raise
                saved.append({
                    "id": cursor.fetchone()[0],
                    "uav_id": uav_ids[code],
                    "uav_code": code,
                    "csv_flight_id": group["csv_flight_id"],
                })
            if on_saved is not None:
                on_saved(cursor, saved)
    return saved


def _select_flights(cursor, where: str = "", params: tuple = (), limit: int | None = None, *, user_id: int):
    # 用户过滤条件仍在 SQL 中强制执行；身份通过参数显式传递。
    if type(user_id) is not int or user_id <= 0:
        raise ValueError("user_id 必须是正整数")
    # task_id 仅用于入库幂等校验，不进入业务查询或模型工具结果。
    public_columns = ("id", "uav_id", "flight_id", "filename", *RECORD_COLUMNS, "version", "created_at")
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


def get_latest_flight(*, user_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            _select_flights(cursor, limit=1, user_id=user_id)
            return cursor.fetchone()


def get_flight_by_id(record_id: int, *, user_id: int) -> dict[str, Any] | None:
    """Look up the database-generated numeric id, not the CSV group label."""
    if type(record_id) is not int or record_id <= 0:
        raise ValueError("id 必须是正整数")
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            _select_flights(cursor, "WHERE flight.id = %s", (record_id,), user_id=user_id)
            return cursor.fetchone()


def get_flights_from_record(record_id: int, limit: int, *, user_id: int) -> list[dict[str, Any]]:
    # 起点必须属于当前用户；同一时间按 ID 倒序，确保起点位于结果首位。
    if type(record_id) is not int or record_id <= 0:
        raise ValueError("id 必须是正整数")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit 必须在 1 到 100 之间")
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            _select_flights(
                cursor,
                "WHERE (flight.start_time, flight.id) <= ("
                "SELECT anchor.start_time, anchor.id FROM flight_records AS anchor "
                "JOIN uavs AS anchor_uav ON anchor_uav.id = anchor.uav_id "
                "WHERE anchor.id = %s AND anchor.user_id = %s AND anchor_uav.user_id = %s)",
                (record_id, user_id, user_id),
                limit,
                user_id=user_id,
            )
            return cursor.fetchall()


def get_flights_from_flight_id(flight_id: str, limit: int, *, user_id: int) -> list[dict[str, Any]]:
    # 用户编号也可作为范围查询起点；无法确认归属时不返回记录。
    if not isinstance(flight_id, str) or not flight_id.strip():
        raise ValueError("flight_id 不能为空")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit 必须在 1 到 100 之间")
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            _select_flights(
                cursor,
                "WHERE (flight.start_time, flight.id) <= ("
                "SELECT anchor.start_time, anchor.id FROM flight_records AS anchor "
                "JOIN uavs AS anchor_uav ON anchor_uav.id = anchor.uav_id "
                "WHERE anchor.flight_id = %s AND anchor.user_id = %s AND anchor_uav.user_id = %s)",
                (flight_id.strip(), user_id, user_id),
                limit,
                user_id=user_id,
            )
            return cursor.fetchall()


def get_recent_flights(limit: int, uav_code: str | None = None, *, uav_id: int | None = None, user_id: int) -> list[dict[str, Any]]:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit 必须在 1 到 100 之间")
    if uav_id is not None and (type(uav_id) is not int or uav_id <= 0):
        raise ValueError("uav_id 必须是正整数")
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            if uav_id is not None:
                _select_flights(cursor, "WHERE uav.id = %s", (uav_id,), limit, user_id=user_id)
            elif uav_code is None:
                _select_flights(cursor, limit=limit, user_id=user_id)
            else:
                _select_flights(cursor, "WHERE uav.uav_code = %s", (normalize_uav_code(uav_code),), limit, user_id=user_id)
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
                _select_flights(cursor, "WHERE flight.id = %s", (record_id,), user_id=user_id)
                return cursor.fetchone()
            cursor.execute(
                "SELECT 1 FROM flight_records AS flight JOIN uavs AS uav ON uav.id = flight.uav_id "
                "WHERE flight.id = %s AND flight.user_id = %s AND uav.user_id = %s",
                (record_id, user_id, user_id),
            )
            if cursor.fetchone() is None:
                return None
            raise FlightRecordVersionConflict


def user_owns_flight_records(record_ids, *, user_id: int):
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
