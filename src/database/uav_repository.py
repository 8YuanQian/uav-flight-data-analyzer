"""Access the new UAV table. Import reuses a UAV; explicit registration rejects duplicates."""

import psycopg

from .connection import get_connection


class UavCodeConflict(ValueError):
    """An explicit registration used an existing UAV code."""


def register_uav(uav_code: str, uav_model: str, manufacturer: str) -> int:
    """Create a UAV separately from CSV import, reporting a duplicate code."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM uavs WHERE uav_code = %s", (uav_code,))
                if cursor.fetchone() is not None:
                    raise UavCodeConflict("飞行器 ID 重复")
                cursor.execute(
                    "INSERT INTO uavs (uav_code, uav_model, manufacturer) "
                    "VALUES (%s, %s, %s) RETURNING id",
                    (uav_code, uav_model, manufacturer),
                )
                return cursor.fetchone()[0]
    except psycopg.errors.UniqueViolation as exc:
        raise UavCodeConflict("飞行器 ID 重复") from exc


def get_or_create_uav(cursor, uav_code: str, uav_model: str, manufacturer: str) -> int:
    """Within an import transaction, reuse an existing UAV without updating its details."""
    cursor.execute(
        "INSERT INTO uavs (uav_code, uav_model, manufacturer) "
        "VALUES (%s, %s, %s) ON CONFLICT (uav_code) DO NOTHING RETURNING id",
        (uav_code, uav_model, manufacturer),
    )
    inserted = cursor.fetchone()
    if inserted is not None:
        return inserted[0]
    cursor.execute("SELECT id FROM uavs WHERE uav_code = %s", (uav_code,))
    return cursor.fetchone()[0]
