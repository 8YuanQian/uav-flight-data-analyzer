"""Celery 任务认领、续租和过期恢复。"""

import json
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from src.common.json_conversion import json_default

from .connection import get_connection


LEASE_SECONDS = 60


class LeaseLost(RuntimeError):
    """当前执行者已经不再拥有任务租约。"""


def _jsonb(value):
    return Jsonb(
        value,
        dumps=lambda data: json.dumps(data, ensure_ascii=False, allow_nan=False, default=json_default),
    )


def register_task(task_id: UUID, user_id: int) -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            # 同一个任务 ID 的重复消息只沿用原状态，不重新生成任务记录。
            cursor.execute(
                """INSERT INTO celery_task_states (task_id, user_id)
                   VALUES (%s, %s)
                   ON CONFLICT (task_id) DO NOTHING""",
                (task_id, user_id),
            )


def get_task_owner(task_id: UUID) -> int | None:
    """查询任务归属；旧 CSV 任务可从上传幂等键恢复归属。"""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT user_id FROM celery_task_states WHERE task_id = %s",
                (task_id,),
            )
            state = cursor.fetchone()
            if state is not None and state[0] is not None:
                return state[0]
            cursor.execute(
                """SELECT user_id FROM csv_upload_idempotency_keys WHERE task_id = %s
                   UNION ALL
                   SELECT user_id FROM flight_report_idempotency_keys WHERE task_id = %s
                   LIMIT 1""",
                (task_id, task_id),
            )
            owner = cursor.fetchone()
            return owner[0] if owner is not None else None


def get_task_state(task_id: UUID) -> dict | None:
    with get_connection() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT status, result FROM celery_task_states WHERE task_id = %s",
                (task_id,),
            )
            return cursor.fetchone()


def claim_task(task_id: UUID, worker_id: str) -> tuple[str, dict | None]:
    with get_connection() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            # 条件 UPDATE 是认领的唯一入口；两个 worker 不能同时拿到同一租约。
            cursor.execute(
                """UPDATE celery_task_states
                   SET status = 'RUNNING', worker_id = %s,
                       heartbeat = clock_timestamp(),
                       lease_deadline = clock_timestamp() + (%s * INTERVAL '1 second')
                   WHERE task_id = %s AND status IN ('PENDING', 'RETRY') AND worker_id IS NULL
                   RETURNING result""",
                (worker_id, LEASE_SECONDS, task_id),
            )
            claimed = cursor.fetchone()
            if claimed is not None:
                return "CLAIMED", claimed["result"]
            cursor.execute(
                "SELECT status, result FROM celery_task_states WHERE task_id = %s",
                (task_id,),
            )
            state = cursor.fetchone()
            if state is None:
                raise ValueError(f"任务状态不存在：{task_id}")
            return state["status"], state["result"]


def renew_lease(task_id: UUID, worker_id: str) -> bool:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """UPDATE celery_task_states
                   SET heartbeat = clock_timestamp(),
                       lease_deadline = clock_timestamp() + (%s * INTERVAL '1 second')
                   WHERE task_id = %s AND worker_id = %s
                     AND status IN ('RUNNING', 'COMMITTED')
                     AND lease_deadline > clock_timestamp()""",
                (LEASE_SECONDS, task_id, worker_id),
            )
            return cursor.rowcount == 1


def assert_lease(task_id: UUID, worker_id: str) -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT 1 FROM celery_task_states
                   WHERE task_id = %s AND worker_id = %s
                     AND status IN ('RUNNING', 'COMMITTED')
                     AND lease_deadline > clock_timestamp()""",
                (task_id, worker_id),
            )
            if cursor.fetchone() is None:
                raise LeaseLost("任务租约已失效")


def check_lease_for_write(cursor, task_id: UUID, worker_id: str) -> None:
    # 入库前核对所有权；提交时再用条件 UPDATE 拦截期间失效的租约。
    # 这里不锁定任务行，心跳线程才能在较长的入库事务中继续续租。
    cursor.execute(
        """SELECT 1 FROM celery_task_states
           WHERE task_id = %s AND worker_id = %s AND status = 'RUNNING'
             AND lease_deadline > clock_timestamp()""",
        (task_id, worker_id),
    )
    if cursor.fetchone() is None:
        raise LeaseLost("写入前任务租约已失效")


def mark_committed_in_transaction(cursor, task_id: UUID, worker_id: str, result: dict) -> None:
    # 条件 UPDATE 是提交栅栏；失去所有权的事务会回滚其全部飞行记录。
    cursor.execute(
        """UPDATE celery_task_states
           SET status = 'COMMITTED', result = %s
           WHERE task_id = %s AND worker_id = %s AND status = 'RUNNING'
             AND lease_deadline > clock_timestamp()""",
        (_jsonb(result), task_id, worker_id),
    )
    if cursor.rowcount != 1:
        raise LeaseLost("提交前任务租约已失效")


def finish_task(task_id: UUID, worker_id: str, result: dict) -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """UPDATE celery_task_states
                   SET status = 'SUCCESS', result = %s,
                       heartbeat = NULL, lease_deadline = NULL
                   WHERE task_id = %s AND worker_id = %s
                     AND status IN ('RUNNING', 'COMMITTED')
                     AND lease_deadline > clock_timestamp()""",
                (_jsonb(result), task_id, worker_id),
            )
            if cursor.rowcount != 1:
                raise LeaseLost("完成任务前租约已失效")


def fail_task(task_id: UUID, worker_id: str) -> bool:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """UPDATE celery_task_states
                   SET status = 'FAILED', heartbeat = NULL, lease_deadline = NULL
                   WHERE task_id = %s AND worker_id = %s
                     AND status IN ('RUNNING', 'COMMITTED')
                     AND lease_deadline > clock_timestamp()""",
                (task_id, worker_id),
            )
            return cursor.rowcount == 1


def reset_expired_leases() -> int:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            # 只重置已过期的 RUNNING/COMMITTED；保留已提交结果供接替者继续处理。
            cursor.execute(
                """UPDATE celery_task_states
                   SET status = 'RETRY', worker_id = NULL,
                       heartbeat = NULL, lease_deadline = NULL
                   WHERE status IN ('RUNNING', 'COMMITTED')
                     AND lease_deadline <= clock_timestamp()"""
            )
            return cursor.rowcount
