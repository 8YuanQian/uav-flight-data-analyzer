"""检查对话续接和检查点连接池；不访问真实模型或数据库。"""

from importlib import import_module
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, StateGraph
from psycopg.rows import dict_row
from psycopg_pool import PoolTimeout

from app.ai_router import ai_flight_router
from src.agent.graph.graph import build_graph
from src.agent.graph.graph_state import UAVGraphState
from src.database import connection as database_connection


def test_build_graph_accepts_external_checkpointer_and_keeps_old_modes():
    saver = InMemorySaver()
    assert build_graph(checkpointer=saver).checkpointer is saver
    assert isinstance(build_graph().checkpointer, InMemorySaver)
    assert build_graph(checkpointing=False).checkpointer is None


def test_api_continues_same_thread_and_clears_previous_tool_data():
    seen = []

    def answer(state: UAVGraphState):
        seen.append((
            state["context"], state["tool_results"], state["message"],
            state["conversation_summary"], state["summary_cursor"],
        ))
        turn_count = sum(item.get("role") == "user" for item in state["message"])
        return {
            "answer": {"answer": f"第 {turn_count} 轮", "sources": []},
            "message": [{"role": "assistant", "content": f"第 {turn_count} 轮"}],
            "context": ["仅本轮资料"],
            "tool_results": ["仅本轮工具结果"],
            "conversation_summary": "已经保存的摘要",
            "summary_cursor": 1,
        }

    builder = StateGraph(UAVGraphState)
    builder.add_node("answer", answer)
    builder.add_edge(START, "answer")
    app = FastAPI()
    app.state.agent_graph = builder.compile(checkpointer=InMemorySaver())
    app.state.db_pool = object()
    app.include_router(ai_flight_router)

    with TestClient(app) as client:
        first = client.post("/ai_flight/model", json={"question": "第一问"})
        assert first.status_code == 200
        thread_id = first.json()["thread_id"]
        assert first.json()["answer"] == "第 1 轮"

        second = client.post(
            "/ai_flight/assistant/model",
            json={"question": "接着问", "thread_id": thread_id},
        )
        assert second.status_code == 200
        assert second.json() == {
            "answer": "第 2 轮", "sources": [], "thread_id": thread_id
        }

        missing = client.post(
            "/ai_flight/model",
            json={"question": "问题", "thread_id": str(uuid4())},
        )
        assert missing.status_code == 404

    assert seen[0][0:2] == ([], [])
    assert seen[1][0:2] == ([], [])
    assert [item["role"] for item in seen[1][2]] == ["user", "assistant", "user"]
    assert seen[1][3:] == ("已经保存的摘要", 1)


def test_checkpoint_pool_uses_required_connection_settings(monkeypatch):
    captured = {}

    def fake_pool(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(database_connection, "ConnectionPool", fake_pool)
    database_connection.create_checkpoint_pool()

    assert captured["min_size"] == 1
    assert captured["max_size"] == 2
    assert captured["timeout"] == 60
    assert captured["open"] is False
    assert captured["kwargs"]["autocommit"] is True
    assert captured["kwargs"]["row_factory"] is dict_row


def test_fastapi_lifespan_sets_up_and_closes_checkpoint_pool(monkeypatch):
    app_module = import_module("app.app")
    events = []

    class Pool:
        def __init__(self, name):
            self.name = name

        def open(self, *, wait):
            events.append((self.name, "open", wait))

        def close(self):
            events.append((self.name, "close"))

    class Saver:
        def __init__(self, pool):
            assert pool.name == "checkpoint"

        def setup(self):
            events.append(("checkpoint", "setup"))

    class Cache:
        def close(self):
            events.append(("cache", "close"))

    monkeypatch.setattr(app_module, "CrossEncoder", lambda name: object())
    monkeypatch.setattr(app_module, "SentenceTransformer", lambda name: object())
    monkeypatch.setattr(app_module, "PostgresSaver", Saver)
    monkeypatch.setattr(app_module, "build_graph", lambda **kwargs: kwargs["checkpointer"])
    monkeypatch.setattr(app_module, "create_connection_pool", lambda *args: Pool("business"))
    monkeypatch.setattr(app_module, "create_checkpoint_pool", lambda: Pool("checkpoint"))
    monkeypatch.setattr(app_module.Redis, "from_url", lambda *args, **kwargs: Cache())

    with TestClient(app_module.create_fastapi_app()) as client:
        assert isinstance(client.app.state.agent_graph, Saver)

    assert events == [
        ("business", "open", False),
        ("checkpoint", "open", True),
        ("checkpoint", "setup"),
        ("checkpoint", "close"),
        ("business", "close"),
        ("cache", "close"),
    ]


def test_checkpoint_pool_timeout_returns_503():
    app_module = import_module("app.app")
    app = FastAPI()
    app.add_exception_handler(PoolTimeout, app_module.database_pool_error_handler)

    @app.get("/timeout")
    def timeout():
        raise PoolTimeout("pool exhausted")

    with TestClient(app) as client:
        response = client.get("/timeout")

    assert response.status_code == 503
    assert response.json() == {"detail": "等待数据库连接超过 60 秒，请稍后重试"}
