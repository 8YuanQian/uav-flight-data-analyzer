"""验证重复消息、租约丢失和终态恢复。"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from celery.exceptions import Reject

from app import task_lease
from src.database import task_lease_repository


@pytest.fixture(autouse=True)
def task_owner(monkeypatch):
    monkeypatch.setattr(task_lease, "get_task_owner", lambda *_: 1)


def test_duplicate_delivery_reuses_saved_result_without_repeating_body(monkeypatch):
    task_id = uuid4()
    calls = []
    statuses = iter([("CLAIMED", None), ("SUCCESS", {"flight_count": 2})])
    monkeypatch.setattr(task_lease, "claim_task", lambda *_: next(statuses))

    class FakeLease:
        def __init__(self, *_):
            self.terminal = False

        def start(self):
            pass

        def stop(self):
            pass

        def assert_owned(self):
            pass

        def finish(self, result):
            calls.append(("finish", result))
            self.terminal = True

    monkeypatch.setattr(task_lease, "TaskLease", FakeLease)
    task = SimpleNamespace(request=SimpleNamespace(id=str(task_id), hostname="worker"))

    def body(lease, previous):
        calls.append("body")
        return {"flight_count": 2}

    assert task_lease.run_leased_task(task, body) == {"flight_count": 2}
    assert task_lease.run_leased_task(task, body) == {"flight_count": 2}
    assert calls == ["body", ("finish", {"flight_count": 2})]


def test_busy_task_keeps_message_for_later_redelivery(monkeypatch):
    monkeypatch.setattr(task_lease, "claim_task", lambda *_: ("RUNNING", None))
    monkeypatch.setattr(task_lease, "sleep", lambda _: None)
    task = SimpleNamespace(request=SimpleNamespace(id=str(uuid4()), hostname="worker"))
    with pytest.raises(Reject) as error:
        task_lease.run_leased_task(task, lambda *_: pytest.fail("不应重复执行任务"))
    assert error.value.requeue is True


def test_lost_lease_does_not_ack_or_delete_upload(monkeypatch):
    monkeypatch.setattr(task_lease, "claim_task", lambda *_: ("CLAIMED", None))
    cleaned = []

    class FakeLease:
        def __init__(self, *_):
            self.terminal = False

        def start(self):
            pass

        def stop(self):
            pass

        def assert_owned(self):
            raise task_lease.LeaseLost("expired")

        def fail(self):
            pytest.fail("失去所有权时不应改写任务状态")

    monkeypatch.setattr(task_lease, "TaskLease", FakeLease)
    task = SimpleNamespace(request=SimpleNamespace(id=str(uuid4()), hostname="worker"))
    with pytest.raises(Reject) as error:
        task_lease.run_leased_task(
            task, lambda lease, _: lease.assert_owned(), cleanup=lambda: cleaned.append(1)
        )
    assert error.value.requeue is True
    assert cleaned == []


def test_expired_lease_reset_only_changes_active_rows(monkeypatch):
    executed = []

    class Cursor:
        rowcount = 2

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def execute(self, sql):
            executed.append(sql)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(task_lease_repository, "get_connection", Connection)
    assert task_lease_repository.reset_expired_leases() == 2
    sql = executed[0]
    assert "status IN ('RUNNING', 'COMMITTED')" in sql
    assert "status = 'RETRY'" in sql
    assert "worker_id = NULL" in sql
    assert "heartbeat = NULL" in sql
    assert "lease_deadline = NULL" in sql
