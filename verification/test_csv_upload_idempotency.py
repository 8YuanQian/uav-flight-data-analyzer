"""验证 CSV 任务提交的用户隔离、重复请求和失败处理。"""

from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from kombu.exceptions import OperationalError

from app import ai_router
from app.database_dependency import database_pool_for_route
from src.auth.security import AuthIdentity, issue_access_token


def build_client(monkeypatch, tmp_path, *, queue_fails=False):
    monkeypatch.setenv("JWT_SECRET_KEY", "i" * 40)
    monkeypatch.setenv("CSV_UPLOAD_DIR", str(tmp_path))
    reservations = {}
    queued = []

    def reserve(user_id, key, task_id):
        old_task_id = reservations.get((user_id, key))
        if old_task_id is not None:
            return old_task_id
        reservations[(user_id, key)] = task_id
        return None

    def release(user_id, key, task_id):
        if reservations.get((user_id, key)) == task_id:
            del reservations[(user_id, key)]

    def send_task(name, args, task_id, retry):
        queued.append((name, args, task_id, retry))
        if queue_fails:
            raise OperationalError("broker unavailable")
        return SimpleNamespace(id=task_id)

    monkeypatch.setattr(ai_router, "reserve_csv_upload", reserve)
    monkeypatch.setattr(ai_router, "release_csv_upload", release)
    monkeypatch.setattr(ai_router, "register_task", lambda *args: None)
    monkeypatch.setattr(ai_router, "get_task_state", lambda task_id: {"status": "RUNNING"})
    app = FastAPI()
    app.state.celery_app = SimpleNamespace(
        send_task=send_task,
        AsyncResult=lambda task_id: SimpleNamespace(status="PENDING"),
    )
    app.include_router(ai_router.ai_flight_router)

    async def no_database_pool():
        yield

    app.dependency_overrides[database_pool_for_route] = no_database_pool
    return TestClient(app), reservations, queued


def upload(client, user_id, key):
    token = issue_access_token(AuthIdentity(user_id, f"user-{user_id}"))
    return client.post(
        "/ai_flight/flights/report",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("flight.csv", BytesIO(b"sample\n1\n"), "text/csv")},
        data={"idempotency_key": str(key)},
    )


def test_same_user_key_only_queues_once_but_other_user_can_use_it(monkeypatch, tmp_path):
    client, reservations, queued = build_client(monkeypatch, tmp_path)
    key = uuid4()
    first = upload(client, 1, key)
    second = upload(client, 1, key)
    other_user = upload(client, 2, key)

    assert first.status_code == 202
    assert second.status_code == 409
    assert set(first.json()) == set(second.json()) == {"task_id", "status"}
    assert second.json() == {"task_id": first.json()["task_id"], "status": "RUNNING"}
    assert other_user.status_code == 202
    assert len(queued) == 2
    assert len(reservations) == 2
    assert queued[0][0] == "uav.process_flights_csv"
    assert queued[0][2:] == (first.json()["task_id"], False)
    assert len(list(tmp_path.glob("*.csv"))) == 2


def test_missing_auth_or_key_does_not_queue(monkeypatch, tmp_path):
    client, reservations, queued = build_client(monkeypatch, tmp_path)
    anonymous = client.post(
        "/ai_flight/flights/report",
        files={"file": ("flight.csv", b"sample", "text/csv")},
        data={"idempotency_key": str(uuid4())},
    )
    assert anonymous.status_code == 401
    token = issue_access_token(AuthIdentity(1, "user-1"))
    no_key = client.post(
        "/ai_flight/flights/report",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("flight.csv", b"sample", "text/csv")},
    )
    assert no_key.status_code == 422
    assert not reservations and not queued


def test_existing_key_uses_celery_status_when_database_state_is_missing(monkeypatch, tmp_path):
    client, _, queued = build_client(monkeypatch, tmp_path)
    key = uuid4()
    first = upload(client, 1, key)
    monkeypatch.setattr(ai_router, "get_task_state", lambda task_id: None)
    client.app.state.celery_app.AsyncResult = lambda task_id: SimpleNamespace(status="SUCCESS")

    repeated = upload(client, 1, key)
    assert repeated.status_code == 409
    assert repeated.json() == {"task_id": first.json()["task_id"], "status": "SUCCESS"}
    assert len(queued) == 1


def test_staging_failure_releases_key_before_queueing(monkeypatch, tmp_path):
    client, reservations, queued = build_client(monkeypatch, tmp_path)

    def fail_stage(_):
        raise OSError("disk full")

    monkeypatch.setattr(ai_router, "stage_csv_upload", fail_stage)
    response = upload(client, 1, uuid4())
    assert response.status_code == 503
    assert not reservations and not queued


def test_uncertain_queue_failure_keeps_key_and_file(monkeypatch, tmp_path):
    client, reservations, queued = build_client(monkeypatch, tmp_path, queue_fails=True)
    key = uuid4()
    first = upload(client, 1, key)
    second = upload(client, 1, key)
    assert first.status_code == 503
    assert second.status_code == 409
    assert second.json() == {"task_id": first.json()["detail"]["task_id"], "status": "RUNNING"}
    assert len(reservations) == len(queued) == 1
    assert len(list(tmp_path.glob("*.csv"))) == 1
