# 使用真实 Graph 路由验证失败上限和退出路径；模型与数据库均使用替身。
import json
from importlib import import_module
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ai_router import _invoke_agent_graph
from src.agent.graph.edges.conditional_security_edge import security_edge
from src.auth.data_scope import use_data_user
from src.auth.security import AuthIdentity, InvalidAccessToken, issue_access_token
from src.schemas import UserQuestion


security_module = import_module("src.agent.graph.nodes.security_node")
graph_module = import_module("src.agent.graph.graph")


@pytest.fixture
def login_token(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "security-limit-test-key-" * 3)
    return issue_access_token(AuthIdentity(7, "test-user"))


def tool_state(name="rag_search", arguments=None, failures=0):
    return {
        "current_tool_call": {
            "name": name,
            "arguments": json.dumps({"query": "drone"} if arguments is None else arguments),
            "call_id": "test-call",
        },
        "security_failure_count": failures,
        "finished": False,
    }


@pytest.mark.parametrize("name, arguments", [
    ("unknown_tool", {}),
    ("rag_search", {"query": "  "}),
    ("get_flight_data", {"limit": 101}),
    ("get_flight_data", {"limit": True}),
    ("get_flight_data", {"record_id": 1, "flight_id": "F-1"}),
])
def test_invalid_arguments_count_as_one_retry(login_token, name, arguments):
    state = tool_state(name, arguments)
    with use_data_user(7, login_token):
        update = security_module.graph_security_node(state)

    assert update["security_failure_count"] == 1
    assert update["current_tool_call"] is None
    assert json.loads(update["message"][0]["output"])["error_code"] == "TOOL_ARGUMENTS_INVALID"
    assert security_edge({**state, **update}) == "agent"


def test_success_does_not_reset_accumulated_failures(login_token):
    state = tool_state(failures=2)
    with use_data_user(7, login_token):
        accepted = security_module.graph_security_node(state)
        state.update(accepted)
        assert state["security_failure_count"] == 2
        assert security_edge(state) == "tool"
        state["current_tool_call"]["arguments"] = '{"query":""}'
        rejected = security_module.graph_security_node(state)

    assert rejected["security_failure_count"] == 3
    assert rejected["finished"] is True
    assert rejected["answer"]["sources"] == []
    assert security_edge({**state, **rejected}) == "end"


def test_graph_stops_at_limit_and_resets_for_next_question(monkeypatch, login_token):
    seen = []

    def invalid_agent(state):
        seen.append(state["security_failure_count"])
        call = tool_state(arguments={"query": ""})["current_tool_call"]
        call["call_id"] = f"test-call-{len(seen)}"
        return {"current_tool_call": call, "message": [{"type": "function_call", **call}], "finished": False}

    def unexpected_tool(*args, **kwargs):
        pytest.fail("校验失败时不应执行工具")

    monkeypatch.setattr(graph_module, "graph_agent_node", invalid_agent)
    monkeypatch.setattr(graph_module, "graph_summary_node", lambda state: {})
    monkeypatch.setattr(graph_module, "graph_tool_node", unexpected_tool)
    graph = graph_module.build_graph()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(agent_graph=graph)))

    with use_data_user(7, login_token):
        first = _invoke_agent_graph(UserQuestion(question="第一问"), request)
        first_state = graph.get_state({"configurable": {"thread_id": first["thread_id"]}}).values
        second = _invoke_agent_graph(
            UserQuestion(question="第二问", thread_id=first["thread_id"]), request,
        )

    assert seen == [0, 1, 2, 0, 1, 2]
    assert first_state["security_failure_count"] == 3
    assert first_state["finished"] is True
    assert first_state["current_tool_call"] is None
    assert first["answer"] == "本次查询多次未能通过参数校验，请调整问题后重试。"
    assert second == first
    # 超限时仍保存工具结果及助手答复，下一轮不会留下未配对的工具调用。
    calls = [item["call_id"] for item in first_state["message"] if item.get("type") == "function_call"]
    outputs = [item["call_id"] for item in first_state["message"] if item.get("type") == "function_call_output"]
    assert calls == outputs
    assert first_state["message"][-1] == {
        "role": "assistant", "content": {"answer": first["answer"], "sources": []},
    }


@pytest.mark.parametrize("scenario, expected_status", [
    ("missing_jwt", 401),
    ("invalid_jwt", 401),
    ("expired_jwt", 401),
    ("identity_mismatch", 401),
    ("not_owned", 403),
    ("database_unavailable", 503),
    ("auth_unavailable", 503),
])
def test_security_errors_exit_graph_without_retry(monkeypatch, login_token, scenario, expected_status):
    calls = []

    def agent(state):
        calls.append("agent")
        return tool_state("get_flight_data", {"record_id": 1})

    def forbidden_operation(*args, **kwargs):
        pytest.fail("认证或权限校验失败后不应执行该操作")

    def unavailable(*args):
        raise RuntimeError("test-only")

    def expired(*args):
        raise InvalidAccessToken("test-only expired token")

    if scenario in {"missing_jwt", "invalid_jwt", "expired_jwt", "identity_mismatch", "auth_unavailable"}:
        monkeypatch.setattr(security_module, "_resources_belong_to_user", forbidden_operation)
    elif scenario == "not_owned":
        monkeypatch.setattr(security_module, "_resources_belong_to_user", lambda *args: False)
    else:
        monkeypatch.setattr(security_module, "_resources_belong_to_user", unavailable)
    if scenario == "expired_jwt":
        monkeypatch.setattr(security_module, "read_access_token", expired)
    elif scenario == "auth_unavailable":
        monkeypatch.setattr(security_module, "read_access_token", unavailable)

    monkeypatch.setattr(graph_module, "graph_agent_node", agent)
    monkeypatch.setattr(graph_module, "graph_summary_node", lambda state: {})
    monkeypatch.setattr(graph_module, "graph_tool_node", forbidden_operation)
    graph = graph_module.build_graph(checkpointing=False)
    app = FastAPI()

    @app.post("/check")
    def check():
        token = None if scenario == "missing_jwt" else (
            "invalid-test-token" if scenario == "invalid_jwt" else login_token
        )
        user_id = 8 if scenario == "identity_mismatch" else 7
        with use_data_user(user_id, token):
            return graph.invoke({"security_failure_count": 0})

    with TestClient(app) as client:
        response = client.post("/check")

    assert response.status_code == expected_status
    assert isinstance(response.json()["detail"], str)
    assert calls == ["agent"]
