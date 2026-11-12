"""数据库连接池的借还、超时和两个进程各自建池的测试。"""

from contextlib import contextmanager
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from psycopg_pool import PoolTimeout

from app.database_dependency import database_pool_for_route
import src.database.connection as database_connection


class FakeConnection:
    def __init__(self):
        self.transactions = 0

    @contextmanager
    def transaction(self):
        self.transactions += 1
        yield


class FakePool:
    def __init__(self, fail=False):
        self.database_connection = FakeConnection()
        self.fail = fail
        self.timeouts = []
        self.returned = []

    @contextmanager
    def connection(self, timeout):
        self.timeouts.append(timeout)
        if self.fail:
            raise PoolTimeout("pool exhausted")
        try:
            yield self.database_connection
        finally:
            self.returned.append(self.database_connection)


def test_only_database_operations_borrow_connections():
    pool = FakePool()
    app = FastAPI()
    app.state.db_pool = pool

    @app.get("/no-db")
    def no_database():
        return {"status": "ok"}

    @app.get("/uses-db", dependencies=[Depends(database_pool_for_route)])
    def uses_database():
        with database_connection.get_connection() as first:
            pass
        with database_connection.get_connection() as second:
            return {"used_pool": first is second is pool.database_connection}

    with TestClient(app) as client:
        assert client.get("/no-db").json() == {"status": "ok"}
        assert pool.timeouts == []
        assert client.get("/uses-db").json() == {"used_pool": True}

    assert pool.timeouts == [60, 60]
    assert pool.returned == [pool.database_connection, pool.database_connection]


def test_connection_is_returned_when_request_fails():
    pool = FakePool()
    app = FastAPI()
    app.state.db_pool = pool

    @app.get("/fails", dependencies=[Depends(database_pool_for_route)])
    def fails():
        with database_connection.get_connection():
            raise RuntimeError("request failed")

    with TestClient(app) as client:
        with pytest.raises(RuntimeError, match="request failed"):
            client.get("/fails")

    assert pool.returned == [pool.database_connection]


def test_pool_timeout_returns_clear_http_error():
    app_module = import_module("app.app")
    pool = FakePool(fail=True)
    app = FastAPI()
    app.state.db_pool = pool
    app.add_exception_handler(
        database_connection.DatabasePoolError, app_module.database_pool_error_handler
    )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/uses-db", dependencies=[Depends(database_pool_for_route)])
    def uses_database():
        with database_connection.get_connection():
            return {"status": "ok"}

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        response = client.get("/uses-db")

    assert response.status_code == 503
    assert response.json()["detail"] == "等待数据库连接超过 60 秒，请稍后重试"
    assert pool.timeouts == [60]
    assert pool.returned == []


def test_cache_hit_does_not_borrow_database_connection(monkeypatch):
    from app.auth_dependencies import require_user
    from src.auth.security import AuthIdentity
    flight_router_module = import_module("app.flight_data_router")
    pool = FakePool()
    app = FastAPI()
    app.state.db_pool = pool
    app.state.cache = object()
    app.include_router(flight_router_module.flight_router)
    app.dependency_overrides[require_user] = lambda: AuthIdentity(1, "test-user")
    monkeypatch.setattr(
        flight_router_module,
        "get_cached_flight_record",
        lambda cache, record_id, **kwargs: {"id": record_id},
    )

    with TestClient(app) as client:
        response = client.get("/flight/flights/17")

    assert response.status_code == 200
    assert pool.timeouts == []


def test_validation_route_does_not_borrow_database_connection():
    flight_router_module = import_module("app.flight_data_router")
    pool = FakePool()
    app = FastAPI()
    app.state.db_pool = pool
    app.include_router(flight_router_module.flight_router)

    with TestClient(app) as client:
        response = client.post(
            "/flight/flights/validate",
            json={
                "uav_code": "UAV-01", "uav_model": "Model", "manufacturer": "Maker",
                "flight_id": "CSV-01", "start_time": "2026-01-01 10:00",
                "end_time": "2026-01-01 10:30", "height": 2, "speed": 3,
                "battery": 90, "temperature": 20,
            },
        )

    assert response.status_code == 200
    assert pool.timeouts == []


def test_report_job_submission_and_status_queries_use_api_pool():
    ai_router_module = import_module("app.ai_router")
    from uuid import uuid4
    from app.auth_dependencies import require_user
    from src.auth.security import AuthIdentity

    pool = FakePool()
    # 保留真实仓储函数，只替换连接和游标，验证借还连接的路径。
    cursor = MagicMock()
    pool.database_connection.cursor = MagicMock()
    pool.database_connection.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.side_effect = [
        (uuid4(),),  # 成功占用报表幂等键。
        (1,),  # 查询任务所属用户。
        {"status": "PENDING", "result": None},
    ]
    app = FastAPI()
    app.state.db_pool = pool

    class FakeCelery:
        def send_task(self, name, args, task_id, retry):
            # 登记幂等键和任务状态各借一次连接，发布消息前已归还。
            assert pool.timeouts == [60, 60]
            assert pool.returned == [pool.database_connection] * 2
            return SimpleNamespace(id=task_id)

        def AsyncResult(self, task_id):
            return SimpleNamespace(
                status="PENDING", successful=lambda: False, failed=lambda: False
            )

    app.state.celery_app = FakeCelery()
    app.include_router(ai_router_module.ai_flight_router)
    app.dependency_overrides[require_user] = lambda: AuthIdentity(1, "test-user")

    with TestClient(app) as client:
        submitted = client.post(
            "/ai_flight/flights/999/report/jobs",
            headers={"Idempotency-Key": str(uuid4())},
        )
        status = client.get(f"/ai_flight/report/jobs/{submitted.json()['task_id']}")

    assert submitted.status_code == 202
    assert submitted.json()["status"] == "PENDING"
    assert status.status_code == 200
    assert pool.timeouts == [60] * 4
    assert pool.returned == [pool.database_connection] * 4
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert "INSERT INTO flight_report_idempotency_keys" in statements[0]
    assert "INSERT INTO celery_task_states" in statements[1]


def test_worker_rejects_missing_record_id(monkeypatch):
    task_module = import_module("app.tasks")
    monkeypatch.setattr(task_module, "get_flight_by_id", lambda record_id, **kwargs: None)

    with pytest.raises(ValueError, match="does not exist"):
        task_module._generate_report(999, None)


def test_api_and_worker_pool_limits(monkeypatch):
    options = []

    def fake_pool(**kwargs):
        options.append(kwargs)
        return object()

    monkeypatch.setattr(database_connection, "ConnectionPool", fake_pool)
    database_connection.create_connection_pool(
        database_connection.API_POOL_MAX_SIZE, "uav-api"
    )
    database_connection.create_connection_pool(
        database_connection.WORKER_POOL_MAX_SIZE, "uav-worker"
    )

    assert [(pool["min_size"], pool["max_size"], pool["timeout"]) for pool in options] == [
        (2, 5, 60),
        (2, 4, 60),
    ]
    assert all(pool["open"] is False for pool in options)


def test_worker_uses_its_own_pool(monkeypatch):
    events = []

    class WorkerPool:
        def open(self, wait):
            events.append(("open", wait))

        @contextmanager
        def connection(self, timeout):
            events.append(("borrow", timeout))
            yield "worker connection"

        def close(self):
            events.append(("close",))

    pool = WorkerPool()
    monkeypatch.setattr(database_connection, "_worker_pool", None)
    monkeypatch.setattr(
        database_connection,
        "create_connection_pool",
        lambda max_size, name: pool,
    )

    database_connection.open_worker_pool()
    with database_connection.get_connection() as connection:
        assert connection == "worker connection"
    database_connection.close_worker_pool()

    assert events == [("open", False), ("borrow", 60), ("close",)]


def test_fastapi_lifespan_opens_and_closes_its_pool(monkeypatch):
    app_module = import_module("app.app")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-key-with-at-least-32-characters")
    events = []

    class LifecyclePool:
        def open(self, wait):
            events.append(("open", wait))

        def close(self):
            events.append(("close",))

    class FakeRedis:
        def close(self):
            events.append(("redis_close",))

    class FakeSaver:
        def __init__(self, pool):
            pass

        def setup(self):
            events.append(("checkpoint_setup",))

    monkeypatch.setattr(app_module, "CrossEncoder", lambda name: object())
    monkeypatch.setattr(app_module, "SentenceTransformer", lambda name: object())
    monkeypatch.setattr(app_module, "build_graph", lambda **kwargs: object())
    monkeypatch.setattr(app_module, "PostgresSaver", FakeSaver)
    monkeypatch.setattr(app_module.Redis, "from_url", lambda *args, **kwargs: FakeRedis())
    monkeypatch.setattr(
        app_module, "create_connection_pool", lambda max_size, name: LifecyclePool()
    )
    monkeypatch.setattr(app_module, "create_checkpoint_pool", lambda: LifecyclePool())

    with TestClient(app_module.create_fastapi_app()):
        assert events == [("open", False), ("open", True), ("checkpoint_setup",)]

    assert events == [
        ("open", False),
        ("open", True),
        ("checkpoint_setup",),
        ("close",),
        ("close",),
        ("redis_close",),
    ]
