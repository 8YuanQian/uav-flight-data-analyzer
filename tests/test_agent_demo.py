# 基础演示测试使用假 Graph 和模型对象，不访问模型服务或数据库。
from importlib import import_module
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from examples import agent_demo
from src.auth.data_scope import require_data_user_id
from src.agent.graph.graph_state import UAVGraphState


def test_demo_injects_models_and_invokes_graph_under_requested_user(monkeypatch):
    graph_module = import_module("src.agent.graph.graph")
    model_module = import_module("src.rag.model_factory")
    models = {"embedding_model": object(), "rerank_model": object()}
    seen = {}

    class FakeGraph:
        def invoke(self, state, *, config):
            seen.update(state=state, config=config, user_id=require_data_user_id())
            return {"answer": {"answer": "测试回答", "sources": []}}

    build = MagicMock(return_value=FakeGraph())
    monkeypatch.setattr(graph_module, "build_graph", build)
    monkeypatch.setattr(model_module, "create_retrieval_models", lambda: models)

    result = agent_demo.run_question("测试问题", 17)

    build.assert_called_once_with(**models)
    assert seen["user_id"] == 17
    assert set(seen["state"]) == UAVGraphState.__required_keys__
    assert seen["state"]["message"] == [{"role": "user", "content": "测试问题"}]
    assert seen["state"]["summary_cursor"] == 0
    assert UUID(seen["config"]["configurable"]["thread_id"])
    assert result["answer"]["answer"] == "测试回答"
    # 演示退出后恢复外层测试的用户上下文。
    assert require_data_user_id() == 1


@pytest.mark.parametrize("arguments", [
    ["--user-id", "0", "--question", "问题"],
    ["--user-id", "17", "--question", "   "],
    ["--question", "问题"],
])
def test_demo_rejects_invalid_input_before_running_graph(monkeypatch, arguments):
    run = MagicMock()
    monkeypatch.setattr(agent_demo, "run_question", run)

    with pytest.raises(SystemExit) as error:
        agent_demo.main(arguments)

    assert error.value.code == 2
    run.assert_not_called()


def test_demo_prints_answer_and_trims_question(monkeypatch, capsys):
    run = MagicMock(return_value={"answer": {"answer": "测试回答", "sources": []}})
    monkeypatch.setattr(agent_demo, "run_question", run)

    agent_demo.main(["--user-id", "17", "--question", "  测试问题  "])

    run.assert_called_once_with("测试问题", 17)
    assert capsys.readouterr().out.strip() == "测试回答"
