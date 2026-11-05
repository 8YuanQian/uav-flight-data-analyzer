import json
from types import SimpleNamespace

from src.agent.answer_guard import find_internal_markers, user_requests_record_id
from src.agent.graph.nodes import agent_node
from src.agent.result_processor import public_flight_analysis, public_flight_records


def _response(answer):
    return SimpleNamespace(
        output=[SimpleNamespace(type="message")],
        output_text=json.dumps(answer, ensure_ascii=False),
    )


def _state():
    return {
        "query": "再重新查一次",
        "context": [],
        "message": [{"role": "user", "content": "再重新查一次"}],
        "conversation_summary": "",
    }


def test_model_facing_flight_result_omits_query_metadata_and_raw_status():
    raw = {
        "total_records": 1,
        "selected_fields": ["id", "uav_code", "battery_start", "battery_end", "anomaly_status"],
        "preview_records": [{
            "id": 1000, "uav_code": "SIM-UAV-0100", "battery_start": 77.0,
            "battery_end": 54.0, "anomaly_status": "normal",
        }],
    }

    public = public_flight_records(raw)

    assert public == {"飞行记录": [{
        "飞行器编号": "SIM-UAV-0100", "起飞电量（%）": 77.0,
        "结束电量（%）": 54.0, "异常状态": "正常",
    }]}
    assert "1000" not in json.dumps(public, ensure_ascii=False)
    assert public_flight_records(raw, include_record_id=user_requests_record_id("记录编号是多少"))[
        "飞行记录"
    ][0]["飞行记录编号"] == 1000
    assert not user_requests_record_id("再重新查一次")


def test_model_facing_analysis_result_uses_business_labels():
    analysis = {
        "status": "success",
        "analysis": [{
            "record_id": 1000, "uav_code": "SIM-UAV-0100", "risk_score": 10,
            "risk_level": "normal",
            "battery_analysis": {"used": 23, "rate_per_minute": 0.5},
            "performance": {"max_speed": 16},
            "warnings": [],
        }],
    }
    assert public_flight_analysis(analysis) == {"飞行分析": [{
        "飞行器编号": "SIM-UAV-0100", "风险得分": 10, "风险等级": "正常",
        "电量消耗（百分点）": 23, "每分钟电量消耗（百分点）": 0.5,
        "飞行表现": {"最大速度": 16}, "风险提示": [],
    }]}


def test_internal_answer_is_retried_without_tool_calls(monkeypatch):
    unsafe = {"answer": "本次查询条件为 limit=1，仅选取 id、uav_code、anomaly_status 字段。", "sources": []}
    safe = {"answer": "最近一次飞行的起飞电量为77%，结束电量为54%。", "sources": []}
    responses = iter((_response(unsafe), _response(safe)))
    calls = []
    monkeypatch.setattr(agent_node, "select_context_with_budget", lambda **kwargs: {"message": []})
    monkeypatch.setattr(agent_node, "count_token", lambda text: 1)
    monkeypatch.setattr(agent_node, "agent_ask_llm", lambda **kwargs: calls.append(kwargs) or next(responses))

    result = agent_node.graph_agent_node(_state())

    assert result["answer"] == safe
    assert result["message"][0]["content"] == safe
    assert len(calls) == 2 and calls[1]["tool_choice"] == "none"
    assert not find_internal_markers(result["answer"]["answer"])


def test_repeated_internal_answer_uses_safe_fallback(monkeypatch):
    unsafe = _response({"answer": "SELECT * FROM flight_records WHERE id = 1000", "sources": []})
    monkeypatch.setattr(agent_node, "select_context_with_budget", lambda **kwargs: {"message": []})
    monkeypatch.setattr(agent_node, "count_token", lambda text: 1)
    monkeypatch.setattr(agent_node, "agent_ask_llm", lambda **kwargs: unsafe)

    result = agent_node.graph_agent_node(_state())

    assert result["answer"] == {"answer": "暂时无法整理答复，请稍后重试。", "sources": []}
    assert not find_internal_markers(result["answer"]["answer"])


def test_raw_record_ids_are_rejected_but_business_record_number_is_allowed():
    assert find_internal_markers("最近一次飞行的数据库记录 id 1000")
    assert find_internal_markers("最近一次飞行的记录 id: 1000")
    assert find_internal_markers("查询结果：id 1000")
    assert not find_internal_markers("飞行记录编号为 1000")
