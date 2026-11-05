# 权限测试不默认绑定用户，确保没有身份时确实拒绝访问。
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import ai_router, flight_data_router, task_lease, tasks
from app.database_dependency import database_pool_for_route
from src.auth.data_scope import require_data_user_id, use_data_user
from src.auth.security import AuthIdentity, issue_access_token
from src.cache import flight_record_cache
from src.database import flight_record_repository, uav_repository


@pytest.fixture(autouse=True)
def data_user():
    yield


class FakeCache:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ex):
        self.values[key] = value
        return True

    def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)


def headers(user_id):
    return {"Authorization": "Bearer " + issue_access_token(AuthIdentity(user_id, f"user-{user_id}"))}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "ownership-test-only-" * 3)
    app = FastAPI()
    app.state.cache = FakeCache()
    app.include_router(flight_data_router.flight_router)
    app.include_router(ai_router.ai_flight_router)

    async def no_pool():
        yield
    app.dependency_overrides[database_pool_for_route] = no_pool
    records = {10: {"id": 10, "uav_id": 1, "uav_code": "UAV-A", "owner": 1},
               20: {"id": 20, "uav_id": 2, "uav_code": "UAV-B", "owner": 2}}

    def get_record(record_id):
        row = records.get(record_id)
        return row if row and row["owner"] == require_data_user_id() else None
    monkeypatch.setattr(flight_record_cache, "get_flight_by_id", get_record)
    monkeypatch.setattr(flight_data_router, "get_user_uavs",
                        lambda limit: [{"id": require_data_user_id()}])
    monkeypatch.setattr(flight_data_router, "get_user_uav",
                        lambda uav_id: {"id": uav_id} if uav_id == require_data_user_id() else None)
    monkeypatch.setattr(flight_record_cache, "get_recent_flights",
                        lambda limit, code, **kw: [row for row in records.values()
                            if row["owner"] == require_data_user_id()
                            and (kw.get("uav_id") is None or row["uav_id"] == kw["uav_id"])])
    return TestClient(app)


@pytest.mark.parametrize("url", ["/flight/uavs", "/flight/uavs/1/flights", "/flight/flights", "/flight/flights/10"])
def test_flight_queries_require_login(client, url):
    assert client.get(url).status_code == 401


def test_uav_list_and_uav_id_queries_only_show_owner(client):
    assert client.get("/flight/uavs", headers=headers(1)).json() == [{"id": 1}]
    assert client.get("/flight/uavs", headers=headers(2)).json() == [{"id": 2}]
    assert client.get("/flight/uavs/1/flights", headers=headers(2)).status_code == 404
    result = client.get("/flight/uavs/1/flights", headers=headers(1))
    assert [row["id"] for row in result.json()] == [10]


def test_warmed_cache_cannot_leak_another_users_record(client):
    assert client.get("/flight/flights/10", headers=headers(1)).status_code == 200
    assert client.get("/flight/flights/10", headers=headers(2)).status_code == 404
    assert client.get("/flight/flights/20", headers=headers(2)).status_code == 200
    assert client.get("/flight/flights/20", headers=headers(1)).status_code == 404


def test_cached_flight_lists_are_separated_by_user(client):
    for user_id, record_id in [(1, 10), (2, 20), (1, 10)]:
        response = client.get("/flight/flights", headers=headers(user_id))
        assert [row["id"] for row in response.json()] == [record_id]


def test_data_access_without_scope_fails_before_database(monkeypatch):
    connect = MagicMock()
    monkeypatch.setattr(flight_record_repository, "get_connection", connect)
    with pytest.raises(PermissionError):
        flight_record_repository.get_latest_flight()
    with pytest.raises(PermissionError):
        flight_record_cache.get_cached_flight_record(FakeCache(), 10)
    connect.assert_not_called()


def test_import_does_not_reuse_another_users_uav():
    cursor = MagicMock()
    cursor.fetchone.side_effect = [None, None]
    with use_data_user(2), pytest.raises(uav_repository.UavOwnershipConflict):
        uav_repository.get_or_create_uav(cursor, "UAV-A", "M", "Maker")
    assert cursor.execute.call_args.args[1] == ("UAV-A", 2)


def test_csv_cannot_override_owner(monkeypatch, flight_group):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (12,)
    monkeypatch.setattr(flight_record_repository, "get_connection", lambda: connection)
    monkeypatch.setattr(flight_record_repository, "get_or_create_uav", lambda *a, **kw: 3)
    with use_data_user(2):
        flight_record_repository.save_flight_groups("csv.csv", [{**flight_group, "user_id": 999}])
    assert cursor.execute.call_args.args[1][3] == 2
    assert 999 not in cursor.execute.call_args.args[1]


def test_unauthorized_update_returns_404_without_touching_cache(client, monkeypatch):
    observed = []
    monkeypatch.setattr(flight_data_router, "update_flight_record",
                        lambda *args: observed.append(require_data_user_id()))
    invalidate = MagicMock()
    monkeypatch.setattr(flight_data_router, "invalidate_flight_record_after_update", invalidate)
    response = client.put("/flight/flights/10", headers=headers(2), json={
        "version": 1, "filename": "forged.csv", "user_id": 1,
        "start_time": "2026-01-01T10:00:00+08:00", "end_time": "2026-01-01T10:30:00+08:00",
        "row_count": 2, "average_height": 20, "max_height": 25, "average_speed": 8, "max_speed": 10,
        "battery_start": 90, "battery_end": 80, "minimum_battery": 80,
        "average_temperature": 25, "max_temperature": 27, "anomaly_status": "normal",
    })
    assert response.status_code == 404
    assert observed == [2]
    invalidate.assert_not_called()


def test_preflight_ownership_failure_prevents_model_and_save(monkeypatch):
    monkeypatch.setattr(tasks, "load_csv_data", lambda _: object())
    monkeypatch.setattr(tasks, "prepare_flights", lambda _: [{"uav_code": "UAV-A"}])
    def denied(codes):
        raise uav_repository.UavOwnershipConflict("飞行器编号不可用于当前账号")
    monkeypatch.setattr(tasks, "validate_import_uavs", denied)
    report, save = MagicMock(), MagicMock()
    monkeypatch.setattr(tasks, "generate_flight_report", report)
    monkeypatch.setattr(tasks, "save_flight_groups", save)
    path = MagicMock()
    path.open.return_value.__enter__.return_value = BytesIO(b"csv")
    with use_data_user(2), pytest.raises(tasks.CsvValidationError, match="当前账号"):
        tasks._process_flights_csv(path, "f.csv", "text/csv", None, None)
    report.assert_not_called()
    save.assert_not_called()


class FakeLease:
    def __init__(self, *args):
        self.terminal = False
    def start(self): pass
    def stop(self): pass
    def assert_owned(self): pass
    def finish(self, result): self.terminal = True
    def fail(self):
        self.terminal = True
        return True


def test_worker_uses_persisted_task_owner_and_restores_context(monkeypatch):
    monkeypatch.setattr(task_lease, "claim_task", lambda *_: ("CLAIMED", None))
    monkeypatch.setattr(task_lease, "get_task_owner", lambda *_: 2)
    monkeypatch.setattr(task_lease, "TaskLease", FakeLease)
    task = SimpleNamespace(request=SimpleNamespace(id=str(uuid4()), hostname="worker"))
    with use_data_user(1):
        assert task_lease.run_leased_task(task, lambda *_: require_data_user_id()) == 2
        assert require_data_user_id() == 1


def test_worker_refuses_tasks_without_owner(monkeypatch):
    monkeypatch.setattr(task_lease, "claim_task", lambda *_: ("CLAIMED", None))
    monkeypatch.setattr(task_lease, "get_task_owner", lambda *_: None)
    monkeypatch.setattr(task_lease, "TaskLease", FakeLease)
    body = MagicMock()
    task = SimpleNamespace(request=SimpleNamespace(id=str(uuid4()), hostname="worker"))
    with pytest.raises(PermissionError):
        task_lease.run_leased_task(task, body)
    body.assert_not_called()


def test_agent_graph_uses_current_verified_user(monkeypatch):
    from langgraph.graph import StateGraph, START, END
    from src.schemas import UserQuestion

    builder = StateGraph(dict)
    builder.add_node("identity", lambda state: {"user": require_data_user_id()})
    builder.add_edge(START, "identity")
    builder.add_edge("identity", END)
    graph = builder.compile()
    monkeypatch.setattr(ai_router, "_invoke_agent_graph",
                        lambda *args: {"answer": str(graph.invoke({})["user"]), "thread_id": str(uuid4())})
    monkeypatch.setattr(ai_router, "add_user_thread", lambda *args: True)
    with use_data_user(1):
        answer = ai_router.invoke_user_agent_graph(
            UserQuestion(question="查询我的飞行记录"), object(), AuthIdentity(2, "B"))
        assert answer["answer"] == "2"
        assert require_data_user_id() == 1


def test_historical_task_result_cannot_bypass_record_ownership(client, monkeypatch):
    task_id = str(uuid4())
    monkeypatch.setattr(ai_router, "get_task_owner", lambda _: 1)
    monkeypatch.setattr(ai_router, "get_task_state", lambda _: {
        "status": "SUCCESS", "result": {"flights": [{"id": 20}]}})
    monkeypatch.setattr(ai_router, "user_owns_flight_records", lambda ids: False)
    client.app.state.celery_app = SimpleNamespace(AsyncResult=lambda _: object())
    assert client.get(f"/ai_flight/report/jobs/{task_id}", headers=headers(1)).status_code == 404

