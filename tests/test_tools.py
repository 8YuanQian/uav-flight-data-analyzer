# 验证当前 Graph 使用的飞行记录工具；数据库操作使用替身。
from src.agent.tools import get_flight_data as tool
import pytest


def test_flight_record_not_found(monkeypatch):
    monkeypatch.setattr(tool, "get_flight_by_id", lambda record_id, **kwargs: None)
    assert tool.get_flight_data(record_id=999, user_id=1) == []


def test_flight_tool_returns_requested_record(monkeypatch):
    monkeypatch.setattr(tool, "get_flight_by_id", lambda record_id, **kwargs: {
        "id": 17, "uav_code": "UAV-01", "filename": "flight.csv",
        "row_count": 2, "max_speed": 10, "max_temperature": 27,
        "minimum_battery": 80,
    })

    result = tool.get_flight_data(record_id=17, user_id=1)

    assert len(result) == 1
    assert result[0]["id"] == 17
    assert result[0]["uav_code"] == "UAV-01"
    assert result[0]["row_count"] == 2


def test_record_id_with_multiple_results_uses_range(monkeypatch):
    calls = []
    monkeypatch.setattr(tool, "get_flights_from_record", lambda record_id, limit, **kwargs:
                        calls.append((record_id, limit)) or [{"id": 17}, {"id": 16}])

    assert tool.get_flight_data(record_id=17, limit=2, user_id=1) == [{"id": 17}, {"id": 16}]
    assert calls == [(17, 2)]


def test_missing_range_start_returns_no_records(monkeypatch):
    monkeypatch.setattr(tool, "get_flights_from_record", lambda record_id, limit, **kwargs: [])
    assert tool.get_flight_data(record_id=999, limit=2, user_id=1) == []


def test_user_flight_id_is_a_range_anchor(monkeypatch):
    calls = []
    monkeypatch.setattr(tool, "get_flights_from_flight_id", lambda flight_id, limit, **kwargs:
                        calls.append((flight_id, limit)) or [{"flight_id": flight_id}])
    assert tool.get_flight_data(flight_id="001", limit=3, user_id=1) == [{"flight_id": "001"}]
    assert calls == [("001", 3)]


def test_flight_id_and_system_id_cannot_both_be_supplied():
    with pytest.raises(ValueError, match="不能同时"):
        tool.get_flight_data(flight_id="001", record_id=17, user_id=1)


@pytest.mark.parametrize("name", ["get_flight_data", "analyze_flight_data"])
def test_tool_definitions_describe_mutually_exclusive_flight_identifiers(name):
    from src.agent.tools.tool_definitions import TOOL_DEFINITIONS

    definition = next(item for item in TOOL_DEFINITIONS if item["name"] == name)
    properties = definition["parameters"]["properties"]
    assert properties["flight_id"]["type"] == "string"
    assert "record_id" in properties["flight_id"]["description"]
    assert "互斥" in properties["flight_id"]["description"]
    assert "flight_id" in properties["record_id"]["description"]
    assert "互斥" in properties["record_id"]["description"]


def test_agent_registry_passes_flight_id_and_public_result_uses_readable_label(monkeypatch):
    from src.agent.result_processor import build_model_result, public_flight_records
    from src.agent.tools import tools_registry

    captured = {}
    def query(**kwargs):
        captured.update(kwargs)
        return [{"flight_id": "001"}]
    monkeypatch.setattr(tools_registry, "get_flight_data", query)
    records = tools_registry.execute_tool("get_flight_data", '{"flight_id":"001","limit":2}', user_id=1)
    result = build_model_result("get_flight_data", records, fields=["flight_id"])
    assert captured["flight_id"] == "001"
    assert captured["limit"] == 2
    assert public_flight_records(result) == {"飞行记录": [{"飞行编号": "001"}]}


@pytest.mark.parametrize("limit", [1, 3])
def test_analysis_uses_user_flight_id_and_preserves_label(monkeypatch, flight_group, limit):
    from src.agent.result_processor import public_flight_analysis
    from src.agent.tools import analyze_flight_data as analysis_tool

    calls = []
    flight = {**flight_group, "id": 17, "flight_id": "001"}
    monkeypatch.setattr(analysis_tool, "get_flights_from_flight_id", lambda flight_id, count, **kwargs:
                        calls.append((flight_id, count)) or [flight])
    result = analysis_tool.analyze_flight_data(flight_id="001", limit=limit, user_id=1)

    assert calls == [("001", limit)]
    assert result["status"] == "success"
    assert result["analysis"][0]["flight_id"] == "001"
    assert public_flight_analysis(result)["飞行分析"][0]["飞行编号"] == "001"


def test_analysis_rejects_conflicting_identifiers_before_query(monkeypatch):
    from unittest.mock import MagicMock
    from src.agent.tools import analyze_flight_data as analysis_tool

    lookup = MagicMock()
    monkeypatch.setattr(analysis_tool, "get_flights_from_flight_id", lookup)
    with pytest.raises(ValueError, match="不能同时"):
        analysis_tool.analyze_flight_data(flight_id="001", record_id=17, user_id=1)
    lookup.assert_not_called()


def test_analysis_returns_not_found_without_falling_back(monkeypatch):
    from unittest.mock import MagicMock
    from src.agent.tools import analyze_flight_data as analysis_tool

    monkeypatch.setattr(analysis_tool, "get_flights_from_flight_id", lambda *_, **kwargs: [])
    recent = MagicMock()
    monkeypatch.setattr(analysis_tool, "get_recent_flights", recent)
    assert analysis_tool.analyze_flight_data(flight_id="missing", user_id=1)["status"] == "failed"
    recent.assert_not_called()


def test_agent_registry_passes_flight_id_to_analysis(monkeypatch):
    from src.agent.tools import tools_registry

    captured = {}
    monkeypatch.setattr(tools_registry, "analyze_flight_data", lambda **kwargs:
                        captured.update(kwargs) or {"status": "success"})
    tools_registry.execute_tool("analyze_flight_data", '{"flight_id":"001","limit":2}', user_id=1)
    assert captured["flight_id"] == "001"
    assert captured["limit"] == 2


def test_recent_flights_receive_uav_code_and_limit(monkeypatch):
    calls = []
    monkeypatch.setattr(tool, "get_recent_flights", lambda limit, code, **kwargs:
                        calls.append((limit, code)) or [{"id": 17}])

    assert tool.get_flight_data(limit=3, uav_code="UAV-01", user_id=1) == [{"id": 17}]
    assert calls == [(3, "UAV-01")]


def test_recent_flights_receive_system_uav_id(monkeypatch):
    calls = []
    monkeypatch.setattr(tool, "get_recent_flights", lambda limit, code, *, uav_id, **kwargs:
                        calls.append((limit, code, uav_id)) or [])

    assert tool.get_flight_data(limit=2, uav_id=8, user_id=1) == []
    assert calls == [(2, None, 8)]
