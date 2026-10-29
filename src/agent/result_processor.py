from src.common.json_conversion import serialize_tool_result
from typing import Any

from src.agent.memory.context_manager import (
    check_tool_result_budget,
    handle_tool_result_overflow,
)


ALLOWED_FLIGHT_FIELDS = {
    "id",
    "uav_id",
    "uav_code",
    "uav_model",
    "manufacturer",
    "start_time",
    "end_time",
    "duration_minutes",
    "row_count",
    "filename",
    "average_height",
    "max_height",
    "average_speed",
    "max_speed",
    "battery_start",
    "battery_end",
    "average_temperature",
    "max_temperature",
    "minimum_battery",
    "anomaly_status",
    "anomaly_reason",
    "created_at",
    "version",
}


def project_flight_records(
    records: list[dict],
    fields: list[str]
) -> dict:
    """根据字段选择数据"""

    if not fields:
        raise ValueError("fields不能为空")

    invalid_fields = set(fields) - ALLOWED_FLIGHT_FIELDS

    if invalid_fields:
        raise ValueError(
            f"不允许选择的字段: {invalid_fields}"
        )

    preview = []

    for record in records:
        selected_record = {
            field: record[field]
            for field in fields
        }

        preview.append(selected_record)

    return {
        "total_records": len(records),
        "selected_fields": fields,
        "preview_records": preview,
    }


def build_model_result(tool_name:str, tool_result, fields:list[str]|None=None):
    if tool_name == "get_flight_data":
        if fields is None:
            raise ValueError("get_flight_data需要指定fields")

        if not isinstance(tool_result, list):
            raise TypeError("get_flight_data结果必须是列表")

        return project_flight_records(
            tool_result,
            fields=fields,
        )

    elif tool_name in ("analyze_flight_data", "rag_search"):
        return tool_result

    else:
        raise ValueError(f"未知工具名: {tool_name}")


def build_error_result_message(type,call_id,error_code,message):
    error_result = {
        "ok": False,
        "error_code": error_code,
        "message": message
    }
    return {
        "message":[{
            "type":"function_call_output",
            "call_id":call_id,
            "output":serialize_tool_result(error_result)
        }],
        "current_tool_call":None
    }






def prepare_tool_result(data: Any) -> dict[str, str]:
    # 1. 序列化一次
    serialized_result = serialize_tool_result(data)

    # 2. 检查实际序列化结果的 Token 数量
    budget = check_tool_result_budget(
        tool_result=serialized_result
    )

    # 3. 根据预算决定交给模型的内容
    if budget["within_budget"]:
        model_output = serialized_result
    else:
        model_output = serialize_tool_result(handle_tool_result_overflow(
            token_count=budget["token_count"],
            max_token=budget["max_token"],
        ))

    # 4. 同时保留原始结果和模型输入
    return {
        "serialized_result": serialized_result,
        "model_output": model_output
    }



