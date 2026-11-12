# 用户身份和 JWT 共用作用域；测试令牌仅用于本地校验。
import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from langgraph.graph import END, START, StateGraph

from app import ai_router
from app.auth_dependencies import user_data_scope
from src.agent.graph.nodes.security_node import graph_security_node
from src.auth.data_scope import require_data_user_id, require_data_user_jwt, use_data_user
from src.auth.security import AuthIdentity, issue_access_token
from src.schemas import UserQuestion


@pytest.fixture
def login_token(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "paired-context-test-key-" * 3)
    return issue_access_token(AuthIdentity(7, "test-user"))


def test_user_and_jwt_restore_together_after_exception():
    with use_data_user(7, "outer-token"):
        with pytest.raises(RuntimeError):
            with use_data_user(8, "inner-token"):
                assert require_data_user_id() == 8
                assert require_data_user_jwt() == "inner-token"
                raise RuntimeError("test-only")
        assert require_data_user_id() == 7
        assert require_data_user_jwt() == "outer-token"
    with pytest.raises(PermissionError):
        require_data_user_jwt()


def test_identity_only_scope_does_not_inherit_another_users_jwt():
    with use_data_user(7, "outer-token"):
        with use_data_user(8):
            assert require_data_user_id() == 8
            with pytest.raises(PermissionError):
                require_data_user_jwt()
        assert require_data_user_jwt() == "outer-token"


def test_concurrent_tasks_keep_user_and_jwt_paired():
    async def worker(user_id):
        with use_data_user(user_id, f"test-token-{user_id}"):
            await asyncio.sleep(0)
            return require_data_user_id(), require_data_user_jwt()
    async def run():
        return await asyncio.gather(worker(7), worker(8))
    assert asyncio.run(run()) == [(7, "test-token-7"), (8, "test-token-8")]


@pytest.mark.parametrize("credential", ["bearer", "cookie"])
def test_authenticated_request_binds_both_values(login_token, credential):
    app = FastAPI()
    @app.get("/scope")
    def inspect_scope(user=Depends(user_data_scope)):
        return {"user_id": require_data_user_id(), "matches": require_data_user_jwt() == login_token}
    headers = ({"Authorization": f"Bearer {login_token}"} if credential == "bearer"
               else {"Cookie": f"uav_access_token={login_token}"})
    with TestClient(app) as client:
        assert client.get("/scope", headers=headers).json() == {"user_id": 7, "matches": True}
    with pytest.raises(PermissionError):
        require_data_user_jwt()


@pytest.mark.parametrize("credential", ["bearer", "cookie"])
def test_agent_entry_preserves_credentials_inside_graph(monkeypatch, login_token, credential):
    builder = StateGraph(dict)
    builder.add_node("identity", lambda state: {
        "user_id": require_data_user_id(), "matches": require_data_user_jwt() == login_token,
    })
    builder.add_edge(START, "identity")
    builder.add_edge("identity", END)
    graph = builder.compile()
    def invoke(*args):
        assert graph.invoke({}) == {"user_id": 7, "matches": True}
        return {"answer": "ok", "thread_id": str(uuid4())}
    monkeypatch.setattr(ai_router, "_invoke_agent_graph", invoke)
    monkeypatch.setattr(ai_router, "add_user_thread", lambda *args: True)
    request = SimpleNamespace(
        headers={"Authorization": f"Bearer {login_token}"} if credential == "bearer" else {},
        cookies={"uav_access_token": login_token} if credential == "cookie" else {},
    )
    with use_data_user(8, "outer-token"):
        ai_router.invoke_user_agent_graph(UserQuestion(question="hello"), request, AuthIdentity(7, "test-user"))
        assert require_data_user_id() == 8
        assert require_data_user_jwt() == "outer-token"


def test_security_node_reads_jwt_from_paired_context(login_token):
    state = {"current_tool_call": {
        "name": "rag_search", "arguments": '{"query":"drone"}', "call_id": "test-call",
    }}
    with use_data_user(7, login_token):
        assert graph_security_node(state)["current_tool_call"]["call_id"] == "test-call"
    with use_data_user(7):
        with pytest.raises(HTTPException) as rejected:
            graph_security_node(state)
        assert rejected.value.status_code == 401
