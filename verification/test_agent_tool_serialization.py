import json
from decimal import Decimal
import pytest

from src.agent import result_processor
from src.agent.graph.nodes import tool_node


def test_flight_tool_passes_numeric_duration_to_agent(monkeypatch):
    # 模拟数据库返回 NUMERIC 时的真实类型，覆盖工具节点到模型输入的完整转换。
    monkeypatch.setattr(
        tool_node,
        "execute_tool",
        lambda **kwargs: [{"id": 7, "duration_minutes": Decimal("36.00")}],
    )
    monkeypatch.setattr(
        result_processor,
        "check_tool_result_budget",
        lambda **kwargs: {"within_budget": True},
    )
    state = {
        "current_tool_call": {
            "name": "get_flight_data",
            "arguments": '{"record_id":7,"fields":["id","duration_minutes"],"user_id":1}',
            "call_id": "call-7",
        }
    }

    result = tool_node.graph_tool_node(state)

    assert result["current_tool_call"] is None
    assert json.loads(result["tool_results"][0]) == {
        "total_records": 1,
        "selected_fields": ["id", "duration_minutes"],
        "preview_records": [{"id": 7, "duration_minutes": 36.0}],
    }
    assert json.loads(result["message"][0]["output"]) == {
        "飞行记录": [{"飞行时长（分钟）": 36.0}],
    }


@pytest.mark.parametrize("selection", [{}, {"fields": None}, {"fields": []}])
def test_omitted_fields_keep_all_retrieved_flight_data(monkeypatch, selection):
    records = [
        {"id": 7, "uav_code": "UAV-01", "duration_minutes": Decimal("36.00"), "max_speed": 12},
        {"id": 8, "uav_code": "UAV-02", "average_height": 25},
    ]
    monkeypatch.setattr(tool_node, "execute_tool", lambda **kwargs: records)
    monkeypatch.setattr(result_processor, "check_tool_result_budget",
                        lambda **kwargs: {"within_budget": True})
    state = {
        "current_tool_call": {
            "name": "get_flight_data",
            "arguments": json.dumps({"limit": 2, **selection, "user_id": 1}),
            "call_id": "call-all",
        }
    }

    result = tool_node.graph_tool_node(state)

    assert result["current_tool_call"] is None
    raw = json.loads(result["tool_results"][0])
    assert raw["total_records"] == 2
    assert raw["selected_fields"] == ["id", "uav_code", "duration_minutes", "max_speed", "average_height"]
    assert raw["preview_records"] == [
        {**records[0], "duration_minutes": 36.0}, records[1]
    ]
    assert json.loads(result["message"][0]["output"]) == {
        "飞行记录": [
            {"飞行器编号": "UAV-01", "飞行时长（分钟）": 36.0, "最大速度": 12},
            {"飞行器编号": "UAV-02", "平均高度": 25},
        ],
    }


def test_no_fields_and_no_records_returns_empty_result():
    assert result_processor.build_model_result("get_flight_data", []) == {
        "total_records": 0, "selected_fields": [], "preview_records": [],
    }


def test_direct_projection_defaults_to_all_fields_without_mutating_input():
    records = [{"uav_code": "UAV-01", "max_speed": 12}]
    result = result_processor.project_flight_records(records)
    assert result["preview_records"] == records
    result["preview_records"][0]["max_speed"] = 20
    assert records[0]["max_speed"] == 12


def test_explicit_invalid_field_is_still_rejected():
    with pytest.raises(ValueError, match="不允许选择"):
        result_processor.build_model_result("get_flight_data", [{"id": 7}], ["password"])
