"""Celery worker 的任务租约和心跳。"""

import logging
import os
from threading import Event, Thread
from time import sleep
from uuid import UUID, uuid4

from celery.exceptions import Reject
from celery.signals import worker_ready, worker_shutdown
from src.auth.data_scope import use_data_user

from src.database.task_lease_repository import (
    LeaseLost, assert_lease, claim_task, fail_task, finish_task,
    check_lease_for_write, mark_committed_in_transaction, renew_lease,
    reset_expired_leases,
    get_task_owner,
)


logger = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 10
WATCHDOG_SECONDS = 15
_watchdog_stop = Event()
_watchdog_thread = None


class TaskLease:
    def __init__(self, task_id: UUID, worker_id: str):
        self.task_id = task_id
        self.worker_id = worker_id
        self.terminal = False
        self._stop = Event()
        self._lost = Event()
        self._thread = Thread(target=self._heartbeat_loop, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=2)

    def _heartbeat_loop(self):
        while not self._stop.wait(HEARTBEAT_SECONDS):
            try:
                # 续租必须带当前 worker_id，失去所有权后不能延长别人的租约。
                if not renew_lease(self.task_id, self.worker_id):
                    self._lost.set()
                    return
            except Exception:
                # 数据库短暂不可用时，下次业务操作仍会重新核验所有权。
                logger.exception("任务心跳续租失败：%s", self.task_id)

    def assert_owned(self):
        if self._lost.is_set():
            raise LeaseLost("任务租约已失效")
        assert_lease(self.task_id, self.worker_id)

    def check_for_write(self, cursor):
        if self._lost.is_set():
            raise LeaseLost("任务租约已失效")
        check_lease_for_write(cursor, self.task_id, self.worker_id)

    def mark_committed(self, cursor, result):
        mark_committed_in_transaction(cursor, self.task_id, self.worker_id, result)

    def finish(self, result):
        finish_task(self.task_id, self.worker_id, result)
        self.terminal = True

    def fail(self):
        self.terminal = fail_task(self.task_id, self.worker_id)
        return self.terminal


def run_leased_task(task, body, *, cleanup=None):
    """认领成功后执行；测试中的直接调用可运行原业务函数。"""
    if task.request.id is None:
        try:
            return body(None, None)
        finally:
            if cleanup is not None:
                cleanup()

    task_id = UUID(task.request.id)
    worker_id = f"{task.request.hostname or 'worker'}:{os.getpid()}:{uuid4().hex}"
    try:
        status, previous_result = claim_task(task_id, worker_id)
    except Exception as exc:
        # 无法查询数据库时不能确认消息，否则任务会永久丢失。
        sleep(5)
        raise Reject("任务状态暂不可用", requeue=True) from exc

    if status == "SUCCESS":
        if cleanup is not None:
            _cleanup_safely(cleanup)
        return previous_result
    if status == "FAILED":
        # 已确定失败的业务任务不再重复执行。
        raise Reject("任务已失败", requeue=False)
    if status != "CLAIMED":
        # 子进程意外退出后的重投可能早于看门狗重置；保留消息等待下一次认领。
        sleep(5)
        raise Reject("任务仍由其他 worker 持有", requeue=True)

    lease = TaskLease(task_id, worker_id)
    lease.start()
    try:
        # 用户编号从任务表恢复；消息参数或 CSV 不能指定数据所有者。
        with use_data_user(get_task_owner(task_id)):
            result = body(lease, previous_result)
        lease.assert_owned()
        lease.finish(result)
        return result
    except LeaseLost as exc:
        # 当前执行者已失去所有权，绝不把这条消息当作成功任务确认。
        raise Reject("任务租约已失效", requeue=True) from exc
    except Exception:
        try:
            if not lease.fail():
                raise Reject("任务租约已失效", requeue=True)
        except Reject:
            raise
        except Exception as exc:
            raise Reject("无法写入任务失败状态", requeue=True) from exc
        raise
    finally:
        lease.stop()
        if lease.terminal and cleanup is not None:
            _cleanup_safely(cleanup)


def _cleanup_safely(cleanup):
    try:
        cleanup()
    except OSError:
        # 清理失败不应把已提交且记录为成功的任务改成失败。
        logger.exception("任务暂存文件清理失败")


def _watchdog_loop():
    while not _watchdog_stop.is_set():
        try:
            recovered = reset_expired_leases()
            if recovered:
                logger.warning("已重置 %s 个过期任务租约", recovered)
        except Exception:
            logger.exception("任务租约看门狗检查失败")
        _watchdog_stop.wait(WATCHDOG_SECONDS)


@worker_ready.connect
def start_task_watchdog(**kwargs):
    global _watchdog_thread
    if _watchdog_thread is None or not _watchdog_thread.is_alive():
        _watchdog_stop.clear()
        _watchdog_thread = Thread(target=_watchdog_loop, name="task-lease-watchdog", daemon=True)
        _watchdog_thread.start()


@worker_shutdown.connect
def stop_task_watchdog(**kwargs):
    _watchdog_stop.set()
    if _watchdog_thread is not None:
        _watchdog_thread.join(timeout=2)
