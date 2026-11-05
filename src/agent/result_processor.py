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

PUBLIC_FLIGHT_FIELDS = {
    "uav_code": "飞行器编号",
    "uav_model": "飞行器型号",
    "manufacturer": "制造商",
    "start_time": "开始时间",
    "end_time": "结束时间",
    "duration_minutes": "飞行时长（分钟）",
    "row_count": "数据行数",
    "filename": "文件名",
    "average_height": "平均高度",
    "max_height": "最大高度",
    "average_speed": "平均速度",
    "max_speed": "最大速度",
    "battery_start": "起飞电量（%）",
    "battery_end": "结束电量（%）",
    "minimum_battery": "最低电量（%）",
    "average_temperature": "平均温度",
    "max_temperature": "最高温度",
    "anomaly_status": "异常状态",
    "anomaly_reason": "异常原因",
}

STATUS_TEXT = {"normal": "正常", "warning": "需关注", "danger": "高风险"}


def project_flight_records(
    records: list[dict],
    fields: list[str] | None = None,
) -> dict:
    """根据字段选择数据"""

    if fields is None or fields == []:
        # 未选择字段时保留各条记录的完整内容，不能按字段并集重建稀疏记录。
        return {
            "total_records": len(records),
            "selected_fields": list(dict.fromkeys(field for record in records for field in record)),
            "preview_records": [dict(record) for record in records],
        }

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


def public_flight_records(data: dict, *, include_record_id: bool = False) -> dict:
    # 原始字段和查询元信息只留给程序；模型只接收用户可读的飞行数据。
    records = []
    for record in data["preview_records"]:
        public_record = {}
        for field, value in record.items():
            if field == "id":
                if include_record_id:
                    public_record["飞行记录编号"] = value
                continue
            label = PUBLIC_FLIGHT_FIELDS.get(field)
            if label is None:
                continue
            if field == "anomaly_status":
                value = STATUS_TEXT.get(value, "未确定")
            public_record[label] = value
        records.append(public_record)
    return {"飞行记录": records}


def public_flight_analysis(data: dict, *, include_record_id: bool = False) -> dict:
    if data.get("status") != "success":
        return {"分析结果": data.get("message", "暂时无法分析飞行记录")}

    results = []
    for item in data["analysis"]:
        public_item = {
            "飞行器编号": item["uav_code"],
            "风险得分": item["risk_score"],
            "风险等级": STATUS_TEXT.get(item["risk_level"], "未确定"),
            "电量消耗（百分点）": item["battery_analysis"]["used"],
            "每分钟电量消耗（百分点）": item["battery_analysis"]["rate_per_minute"],
            "飞行表现": {
                PUBLIC_FLIGHT_FIELDS[field]: value
                for field, value in item["performance"].items()
                if field in PUBLIC_FLIGHT_FIELDS
            },
            "风险提示": item["warnings"],
        }
        if include_record_id:
            public_item["飞行记录编号"] = item["record_id"]
        results.append(public_item)
    return {"飞行分析": results}


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


def prepare_tool_result(data: Any, *, model_data: Any = None) -> dict[str, str]:
    # 1. 序列化一次
    serialized_result = serialize_tool_result(data)
    serialized_model_result = serialize_tool_result(data if model_data is None else model_data)

    # 2. 按真正交给模型的内容检查 Token 数量
    budget = check_tool_result_budget(
        tool_result=serialized_model_result
    )

    # 3. 根据预算决定交给模型的内容
    if budget["within_budget"]:
        model_output = serialized_model_result
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



