"""Access the new UAV table. Import reuses a UAV; explicit registration rejects duplicates."""

import psycopg
from uuid import UUID

from src.common.uav_code import normalize_uav_code
from src.auth.data_scope import require_data_user_id
from psycopg.rows import dict_row

from .connection import get_connection


class UavCodeConflict(ValueError):
    """An explicit registration used an existing UAV code."""


class UavOwnershipConflict(ValueError):
    pass


def register_uav(uav_code: str, uav_model: str, manufacturer: str) -> int:
    """Create a UAV separately from CSV import, reporting a duplicate code."""
    uav_code = normalize_uav_code(uav_code)
    user_id = require_data_user_id()
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM uavs WHERE uav_code = %s", (uav_code,))
                if cursor.fetchone() is not None:
                    raise UavCodeConflict("飞行器 ID 重复")
                cursor.execute(
                    "INSERT INTO uavs (uav_code, uav_model, manufacturer, user_id) "
                    "VALUES (%s, %s, %s, %s) RETURNING id",
                    (uav_code, uav_model, manufacturer, user_id),
                )
                return cursor.fetchone()[0]
    except psycopg.errors.UniqueViolation as exc:
        raise UavCodeConflict("飞行器 ID 重复") from exc


def get_or_create_uav(cursor, uav_code: str, uav_model: str, manufacturer: str, *, task_id: UUID | None = None) -> int:
    """Within an import transaction, reuse an existing UAV without updating its details."""
    uav_code = normalize_uav_code(uav_code)
    user_id = require_data_user_id()
    cursor.execute(
        "INSERT INTO uavs (uav_code, uav_model, manufacturer, task_id, user_id) "
        "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (uav_code) DO NOTHING RETURNING id",
        (uav_code, uav_model, manufacturer, task_id, user_id),
    )
    inserted = cursor.fetchone()
    if inserted is not None:
        return inserted[0]
    # 已有飞行器只复用其 ID，不覆盖首次创建它的 task_id。
    cursor.execute("SELECT id FROM uavs WHERE uav_code = %s AND user_id = %s", (uav_code, user_id))
    owned = cursor.fetchone()
    if owned is None:
        raise UavOwnershipConflict("飞行器编号不可用于当前账号，请核对编号")
    return owned[0]


def validate_import_uavs(codes):
    user_id = require_data_user_id()
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM uavs WHERE uav_code = ANY(%s) AND user_id IS DISTINCT FROM %s LIMIT 1",
            (list({normalize_uav_code(code) for code in codes}), user_id),
        )
        if cursor.fetchone() is not None:
            raise UavOwnershipConflict("飞行器编号不可用于当前账号，请核对编号")


def get_user_uavs(limit=100):
    user_id = require_data_user_id()
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT id, uav_code, uav_model, manufacturer FROM uavs "
            "WHERE user_id = %s ORDER BY id DESC LIMIT %s", (user_id, limit),
        )
        return cursor.fetchall()


def get_user_uav(uav_id):
    user_id = require_data_user_id()
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT id, uav_code, uav_model, manufacturer FROM uavs WHERE id = %s AND user_id = %s",
            (uav_id, user_id),
        )
        return cursor.fetchone()
