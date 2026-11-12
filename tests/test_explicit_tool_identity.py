# 验证身份只由安全节点注入，工具与查询层使用显式用户参数。
import json
from importlib import import_module
from unittest.mock import MagicMock

import pytest

from src.agent.graph.nodes import security_node, tool_node
from src.agent.tools import tools_registry
from src.agent.tools.tool_definitions import TOOL_DEFINITIONS
from src.auth.data_scope import use_data_user
from src.auth.security import AuthIdentity, issue_access_token
from src.cache import flight_record_cache
from src.database import flight_record_repository


@pytest.fixture
def login_token(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "explicit-identity-test-" * 3)
    return issue_access_token(AuthIdentity(7, "test-user"))


def state_for(name, arguments):
    call = {"name": name, "call_id": "test-call", "arguments": json.dumps(arguments)}
    return {"current_tool_call": call, "message": [{"type": "function_call", **call}]}


@pytest.mark.parametrize("name, arguments", [
    ("get_flight_data", {"limit": 1}),
    ("analyze_flight_data", {"limit": 1}),
    ("rag_search", {"query": "drone"}),
])
def test_security_injects_verified_identity_without_changing_model_history(login_token, name, arguments):
    state = state_for(name, arguments)
    original = json.dumps(state)
    with use_data_user(7, login_token):
        update = security_node.graph_security_node(state)

    assert json.loads(update["current_tool_call"]["arguments"])["user_id"] == 7
    assert json.dumps(state) == original
    definition = next(item for item in TOOL_DEFINITIONS if item["name"] == name)
    assert "user_id" not in definition["parameters"]["properties"]


@pytest.mark.parametrize("forged_user", [7, 999])
def test_model_cannot_supply_identity(monkeypatch, login_token, forged_user):
    ownership = MagicMock()
    monkeypatch.setattr(security_node, "_resources_belong_to_user", ownership)
    with use_data_user(7, login_token):
        update = security_node.graph_security_node(
            state_for("get_flight_data", {"user_id": forged_user, "record_id": 1})
        )

    assert update["current_tool_call"] is None
    assert update["security_failure_count"] == 1
    ownership.assert_not_called()


@pytest.mark.parametrize("name", ["get_flight_data", "analyze_flight_data", "rag_search"])
def test_tool_node_separates_execution_identity_from_business_arguments(monkeypatch, name):
    observed = {}

    def execute(tool_name, tool_arguments, *, user_id, **models):
        observed.update(name=tool_name, arguments=json.loads(tool_arguments), user_id=user_id)
        return {"status": "failed", "message": "没有飞行记录"} if name == "analyze_flight_data" else []

    monkeypatch.setattr(tool_node, "execute_tool", execute)
    result = tool_node.graph_tool_node(state_for(name, {"user_id": 7}))

    assert observed == {"name": name, "arguments": {}, "user_id": 7}
    assert result["current_tool_call"] is None


def test_tool_node_without_injected_identity_never_executes(monkeypatch):
    execute = MagicMock()
    monkeypatch.setattr(tool_node, "execute_tool", execute)
    with pytest.raises(KeyError, match="user_id"):
        tool_node.graph_tool_node(state_for("get_flight_data", {"limit": 1}))
    execute.assert_not_called()


@pytest.mark.parametrize("name", ["get_flight_data", "analyze_flight_data"])
def test_registry_uses_explicit_identity_even_if_business_arguments_contain_another_user(monkeypatch, name):
    function = MagicMock(return_value=[])
    monkeypatch.setattr(tools_registry, name, function)
    tools_registry.execute_tool(name, '{"user_id":999,"limit":1}', user_id=7)
    assert function.call_args.kwargs["user_id"] == 7


@pytest.mark.parametrize("user_id", [None, True, 0, -1, "7"])
def test_registry_rejects_invalid_execution_identity(user_id):
    with pytest.raises(ValueError, match="user_id"):
        tools_registry.execute_tool("get_flight_data", "{}", user_id=user_id)


@pytest.mark.parametrize("module_name, function_name", [
    ("get_flight_data", "get_flight_data"),
    ("analyze_flight_data", "analyze_flight_data"),
])
@pytest.mark.parametrize("arguments", [
    {}, {"record_id": 17}, {"record_id": 17, "limit": 2},
    {"flight_id": "CSV-01", "limit": 2}, {"uav_code": "UAV-01"}, {"uav_id": 3},
])
def test_tool_query_chain_uses_explicit_user_without_reading_context(
    monkeypatch, flight_group, module_name, function_name, arguments,
):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    row = {**flight_group, "id": 17, "uav_id": 3, "flight_id": "CSV-01"}
    cursor.fetchone.return_value = row
    cursor.fetchall.return_value = [row]
    monkeypatch.setattr(flight_record_repository, "get_connection", lambda: connection)
    ambient_user = MagicMock(side_effect=AssertionError("查询层不应读取用户上下文"))
    monkeypatch.setattr(flight_record_repository, "require_data_user_id", ambient_user)
    function = getattr(import_module("src.agent.tools." + module_name), function_name)

    function(**arguments, user_id=7)

    ambient_user.assert_not_called()
    sql, params = cursor.execute.call_args.args
    assert "uav.user_id = %s AND flight.user_id = %s" in sql
    assert params[:2] == (7, 7)
    if "anchor." in sql:
        assert params[3:5] == (7, 7)


def test_cache_keys_and_database_reads_use_the_same_explicit_user(monkeypatch):
    values = {}
    cache = MagicMock()
    cache.get.side_effect = values.get
    cache.set.side_effect = lambda key, value, ex: values.__setitem__(key, value) or True
    users = []

    def read(record_id, *, user_id):
        users.append(user_id)
        return {"id": record_id, "owner": user_id}

    monkeypatch.setattr(flight_record_cache, "get_flight_by_id", read)
    assert flight_record_cache.get_cached_flight_record(cache, 17, user_id=7)["owner"] == 7
    assert flight_record_cache.get_cached_flight_record(cache, 17, user_id=8)["owner"] == 8
    assert flight_record_cache.get_cached_flight_record(cache, 17, user_id=7)["owner"] == 7
    assert users == [7, 8]
    assert set(values) == {
        "uav:users:7:flight_records:by_id:v2:17", "uav:users:8:flight_records:by_id:v2:17",
    }


def test_verified_call_executes_after_identity_context_has_ended(monkeypatch, login_token):
    monkeypatch.setattr(security_node, "_resources_belong_to_user", lambda *args: True)
    with use_data_user(7, login_token):
        verified = security_node.graph_security_node(state_for("get_flight_data", {"record_id": 17}))

    # 安全校验的请求作用域已经结束，后续真实工具分派仍只使用注入的用户编号。
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = {"id": 17, "flight_id": "CSV-01", "uav_code": "UAV-01"}
    monkeypatch.setattr(flight_record_repository, "get_connection", lambda: connection)
    ambient_user = MagicMock(side_effect=AssertionError("不应重新读取身份上下文"))
    monkeypatch.setattr(flight_record_repository, "require_data_user_id", ambient_user)

    result = tool_node.graph_tool_node(verified)

    ambient_user.assert_not_called()
    assert cursor.execute.call_args.args[1] == (7, 7, 17)
    assert json.loads(result["message"][0]["output"]) == {
        "飞行记录": [{"飞行编号": "CSV-01", "飞行器编号": "UAV-01"}],
    }
