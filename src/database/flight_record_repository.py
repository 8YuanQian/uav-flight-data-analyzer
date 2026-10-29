"""Read and write per-flight summaries in the new UAV-linked table."""

from typing import Any

from psycopg.rows import dict_row

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


def save_flight_groups(filename: str, groups: list[dict]) -> list[dict]:
    """Commit all UAVs and flights together; no CSV flight_id enters the SQL insert."""
    saved = []
    with get_connection() as conn:
        with conn.cursor() as cursor:
            uav_ids = {}
            for group in groups:
                code = group["uav_code"]
                if code not in uav_ids:
                    uav_ids[code] = get_or_create_uav(
                        cursor, code, group["uav_model"], group["manufacturer"]
                    )
                columns = ("uav_id", "filename", *RECORD_COLUMNS)
                values = (uav_ids[code], filename, *(group[field] for field in RECORD_COLUMNS))
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
    return saved


def _select_flights(cursor, where: str = "", params: tuple = (), limit: int | None = None):
    query = (
        "SELECT flight.*, uav.uav_code, uav.uav_model, uav.manufacturer "
        "FROM flight_records AS flight JOIN uavs AS uav ON uav.id = flight.uav_id "
        + where + " ORDER BY flight.start_time DESC, flight.id DESC"
    )
    if limit is not None:
        query += " LIMIT %s"
        params += (limit,)
    cursor.execute(query, params)


def get_latest_flight() -> dict[str, Any] | None:
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            _select_flights(cursor, limit=1)
            return cursor.fetchone()


def get_flight_by_id(record_id: int) -> dict[str, Any] | None:
    """Look up the database-generated numeric id, not the CSV group label."""
    if type(record_id) is not int or record_id <= 0:
        raise ValueError("id 必须是正整数")
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            _select_flights(cursor, "WHERE flight.id = %s", (record_id,))
            return cursor.fetchone()


def get_recent_flights(limit: int, uav_code: str | None = None) -> list[dict[str, Any]]:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit 必须在 1 到 100 之间")
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            if uav_code is None:
                _select_flights(cursor, limit=limit)
            else:
                _select_flights(cursor, "WHERE uav.uav_code = %s", (uav_code,), limit)
            return cursor.fetchall()


def update_flight_record(record_id: int, expected_version: int, filename: str, values: dict):
    """Atomically replace a summary only when its version still matches."""
    if type(record_id) is not int or record_id <= 0:
        raise ValueError("id 必须是正整数")
    assignments = ", ".join(f"{column} = %s" for column in RECORD_COLUMNS)
    parameters = (filename, *(values[column] for column in RECORD_COLUMNS), record_id, expected_version)
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"UPDATE flight_records SET filename = %s, {assignments}, "
                "version = version + 1 WHERE id = %s AND version = %s RETURNING id",
                parameters,
            )
            if cursor.fetchone() is not None:
                _select_flights(cursor, "WHERE flight.id = %s", (record_id,))
                return cursor.fetchone()
            cursor.execute("SELECT 1 FROM flight_records WHERE id = %s", (record_id,))
            if cursor.fetchone() is None:
                return None
            raise FlightRecordVersionConflict
