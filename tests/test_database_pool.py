"""数据库连接池的借还、超时和两个进程各自建池的测试。"""

from contextlib import contextmanager
from importlib import import_module
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from psycopg_pool import PoolTimeout

from app.database_dependency import database_pool_for_route
import src.database.connection as database_connection


@pytest.fixture(autouse=True)
def clean():
    """这些测试使用假连接，不访问父 conftest 指定的测试数据库。"""
    yield


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
    flight_router_module = import_module("app.flight_data_router")
    pool = FakePool()
    app = FastAPI()
    app.state.db_pool = pool
    app.state.cache = object()
    app.include_router(flight_router_module.flight_router)
    monkeypatch.setattr(
        flight_router_module,
        "get_cached_flight_analysis",
        lambda cache, analysis_id: {"id": analysis_id},
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
            json={"time": 1, "height": 2, "speed": 3, "battery": 90, "temperature": 20},
        )

    assert response.status_code == 200
    assert pool.timeouts == []


def test_celery_routes_do_not_borrow_api_connection():
    ai_router_module = import_module("app.ai_router")
    pool = FakePool()
    app = FastAPI()
    app.state.db_pool = pool

    class FakeCelery:
        def send_task(self, name, args, retry):
            return SimpleNamespace(id="task-1")

        def AsyncResult(self, task_id):
            return SimpleNamespace(
                status="PENDING", successful=lambda: False, failed=lambda: False
            )

    app.state.celery_app = FakeCelery()
    app.include_router(ai_router_module.ai_flight_router)

    with TestClient(app) as client:
        submitted = client.post("/ai_flight/flights/999/report/jobs")
        status = client.get("/ai_flight/report/jobs/task-1")

    assert submitted.status_code == 202
    assert submitted.json() == {"task_id": "task-1", "status": "PENDING"}
    assert status.status_code == 200
    assert pool.timeouts == []


def test_worker_rejects_missing_analysis_id(monkeypatch):
    task_module = import_module("app.tasks")
    monkeypatch.setattr(task_module, "get_flight_analysis", lambda analysis_id: None)

    with pytest.raises(ValueError, match="does not exist"):
        task_module.generate_flight_report_task.run(999)


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
        (2, 15, 60),
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
