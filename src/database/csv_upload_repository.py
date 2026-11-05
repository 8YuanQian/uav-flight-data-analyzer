"""保存用户 CSV 上传请求的幂等键。"""

from uuid import UUID

from .connection import get_connection


class UploadUserNotFound(ValueError):
    pass


def reserve_csv_upload(user_id: int, idempotency_key: UUID, task_id: UUID) -> UUID | None:
    """原子占用键；重复时返回原任务 ID，新键返回 None。"""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            # 用户 ID 只取自已验证的 JWT；INSERT 的主键约束负责拦截并发重复提交。
            cursor.execute(
                """INSERT INTO csv_upload_idempotency_keys
                       (user_id, idempotency_key, task_id)
                   SELECT id, %s, %s FROM users WHERE id = %s
                   ON CONFLICT (user_id, idempotency_key) DO NOTHING
                   RETURNING task_id""",
                (idempotency_key, task_id, user_id),
            )
            if cursor.fetchone() is not None:
                return None

            # 冲突行在另一事务提交后可见，返回其原任务 ID 供用户查询状态。
            cursor.execute(
                """SELECT task_id FROM csv_upload_idempotency_keys
                   WHERE user_id = %s AND idempotency_key = %s""",
                (user_id, idempotency_key),
            )
            existing = cursor.fetchone()
            if existing is None:
                raise UploadUserNotFound(user_id)
            return existing[0]


def release_csv_upload(user_id: int, idempotency_key: UUID, task_id: UUID) -> None:
    """仅在文件暂存失败、任务尚未投递时释放本次占用。"""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """DELETE FROM csv_upload_idempotency_keys
                   WHERE user_id = %s AND idempotency_key = %s AND task_id = %s""",
                (user_id, idempotency_key, task_id),
            )
