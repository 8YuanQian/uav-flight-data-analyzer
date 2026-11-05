"""验证单条报表请求去重，以及任务结果只能由所有者查询。"""

from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from kombu.exceptions import OperationalError

from app import ai_router
from app.database_dependency import database_pool_for_route
from src.auth.security import AuthIdentity, issue_access_token


def build_client(monkeypatch, *, queue_fails=False):
    monkeypatch.setenv("JWT_SECRET_KEY", "i" * 40)
    reservations = {}
    owners = {}
    queued = []

    def reserve(user_id, key, record_id, task_id):
        existing = reservations.get((user_id, key))
        if existing is not None:
            return existing
        reservations[(user_id, key)] = (task_id, record_id)
        return None

    def release(user_id, key, task_id):
        if reservations.get((user_id, key), (None,))[0] == task_id:
            del reservations[(user_id, key)]

    def register(task_id, user_id):
        owners[task_id] = user_id

    def send_task(name, args, task_id, retry):
        queued.append((name, args, task_id, retry))
        if queue_fails:
            raise OperationalError("broker unavailable")
        return SimpleNamespace(id=task_id)

    def async_result(task_id):
        return SimpleNamespace(
            status="PENDING", successful=lambda: False, failed=lambda: False
        )

    monkeypatch.setattr(ai_router, "reserve_flight_report_job", reserve)
    monkeypatch.setattr(ai_router, "release_flight_report_job", release)
    monkeypatch.setattr(ai_router, "register_task", register)
    monkeypatch.setattr(ai_router, "get_task_owner", lambda task_id: owners.get(task_id))
    monkeypatch.setattr(ai_router, "get_task_state", lambda task_id: {"status": "PENDING"})

    app = FastAPI()
    app.state.celery_app = SimpleNamespace(send_task=send_task, AsyncResult=async_result)
    app.include_router(ai_router.ai_flight_router)

    async def no_database_pool():
        yield

    app.dependency_overrides[database_pool_for_route] = no_database_pool
    return TestClient(app), reservations, owners, queued


def auth_header(user_id):
    token = issue_access_token(AuthIdentity(user_id, f"user-{user_id}"))
    return {"Authorization": f"Bearer {token}"}


def test_same_user_and_key_only_queue_one_report(monkeypatch):
    client, reservations, owners, queued = build_client(monkeypatch)
    key = uuid4()
    headers = {**auth_header(1), "Idempotency-Key": str(key)}
    first = client.post("/ai_flight/flights/17/report/jobs", headers=headers)
    second = client.post("/ai_flight/flights/17/report/jobs", headers=headers)
    different_record = client.post("/ai_flight/flights/18/report/jobs", headers=headers)
    other_user = client.post(
        "/ai_flight/flights/17/report/jobs",
        headers={**auth_header(2), "Idempotency-Key": str(key)},
    )

    assert [response.status_code for response in (first, second, different_record, other_user)] == [202, 409, 409, 202]
    assert second.json()["detail"]["task_id"] == first.json()["task_id"]
    assert different_record.json()["detail"]["message"] == "该幂等键已用于另一条飞行记录"
    assert len(reservations) == len(queued) == 2
    assert queued[0][0] == "uav.generate_flight_report"
    assert queued[0][2:] == (first.json()["task_id"], False)
    assert owners[UUID(first.json()["task_id"])] == 1


def test_result_lookup_requires_owner_before_reading_celery(monkeypatch):
    client, _, _, _ = build_client(monkeypatch)
    key = uuid4()
    submitted = client.post(
        "/ai_flight/flights/17/report/jobs",
        headers={**auth_header(1), "Idempotency-Key": str(key)},
    )
    task_id = submitted.json()["task_id"]
    assert client.get(f"/ai_flight/report/jobs/{task_id}").status_code == 401
    assert client.get(f"/ai_flight/report/jobs/{task_id}", headers=auth_header(2)).status_code == 404
    own = client.get(f"/ai_flight/report/jobs/{task_id}", headers=auth_header(1))
    assert own.status_code == 200
    assert own.json() == {"task_id": task_id, "status": "PENDING"}
    assert client.get(f"/ai_flight/report/jobs/{uuid4()}", headers=auth_header(1)).status_code == 404


def test_missing_key_and_uncertain_delivery_do_not_make_second_task(monkeypatch):
    client, reservations, _, queued = build_client(monkeypatch, queue_fails=True)
    assert client.post(
        "/ai_flight/flights/17/report/jobs", headers=auth_header(1)
    ).status_code == 422
    key = uuid4()
    headers = {**auth_header(1), "Idempotency-Key": str(key)}
    first = client.post("/ai_flight/flights/17/report/jobs", headers=headers)
    second = client.post("/ai_flight/flights/17/report/jobs", headers=headers)
    assert first.status_code == 503
    assert second.status_code == 409
    assert second.json()["detail"]["task_id"] == first.json()["detail"]["task_id"]
    assert len(reservations) == len(queued) == 1
