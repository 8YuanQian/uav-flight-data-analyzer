"""保存单条飞行报告任务的用户幂等键。"""

from uuid import UUID

from .connection import get_connection


class ReportUserNotFound(ValueError):
    """幂等键对应的登录用户已不存在。"""


def reserve_flight_report_job(
    user_id: int, idempotency_key: UUID, record_id: int, task_id: UUID
) -> tuple[UUID, int] | None:
    """原子占用键；重复时返回原任务 ID 和原飞行记录 ID。"""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO flight_report_idempotency_keys
                       (user_id, idempotency_key, record_id, task_id)
                   SELECT id, %s, %s, %s FROM users WHERE id = %s
                   ON CONFLICT (user_id, idempotency_key) DO NOTHING
                   RETURNING task_id""",
                (idempotency_key, record_id, task_id, user_id),
            )
            if cursor.fetchone() is not None:
                return None

            cursor.execute(
                """SELECT task_id, record_id FROM flight_report_idempotency_keys
                   WHERE user_id = %s AND idempotency_key = %s""",
                (user_id, idempotency_key),
            )
            existing = cursor.fetchone()
            if existing is None:
                raise ReportUserNotFound(user_id)
            return existing[0], existing[1]


def release_flight_report_job(user_id: int, idempotency_key: UUID, task_id: UUID) -> None:
    """仅在任务状态尚未成功登记时释放本次占用。"""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """DELETE FROM flight_report_idempotency_keys
                   WHERE user_id = %s AND idempotency_key = %s AND task_id = %s""",
                (user_id, idempotency_key, task_id),
            )


def get_report_record_id(task_id: UUID) -> int | None:
    from src.auth.data_scope import require_data_user_id
    user_id = require_data_user_id()
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT record_id FROM flight_report_idempotency_keys WHERE task_id = %s AND user_id = %s", (task_id, user_id))
        row = cursor.fetchone()
        return row[0] if row else None
