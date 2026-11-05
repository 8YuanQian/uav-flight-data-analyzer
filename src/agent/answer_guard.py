"""检查最终回答是否包含工具和数据库的内部表达。"""

import re


_INTERNAL_NAMES = (
    "get_flight_data", "analyze_flight_data", "rag_search",
    "flight_records", "flight_analyses", "selected_fields", "preview_records",
    "total_records", "function_call_output", "tool_results", "record_id",
    "uav_id", "uav_code", "uav_model", "csv_flight_id", "duration_minutes",
    "row_count", "start_time", "end_time", "average_height", "max_height",
    "average_speed", "max_speed", "battery_start", "battery_end",
    "minimum_battery", "average_temperature", "max_temperature",
    "anomaly_status", "anomaly_reason", "risk_score", "risk_level",
    "battery_analysis", "rate_per_minute", "created_at",
)
_INTERNAL_NAME_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:" + "|".join(map(re.escape, _INTERNAL_NAMES)) + r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_SQL_PATTERN = re.compile(
    r"\bSELECT\b[\s\S]{0,160}\bFROM\b|\bINSERT\s+INTO\b|"
    r"\bUPDATE\s+\w+\s+SET\b|\bDELETE\s+FROM\b|"
    r"\bWHERE\s+\w+\s*(?:=|<|>)|\bORDER\s+BY\b",
    re.IGNORECASE,
)
_PARAMETER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:limit|fields|record_id|uav_code)\s*[:=]\s*(?:\d|[\[{'\"A-Za-z_])",
    re.IGNORECASE,
)
_PROCESS_PATTERN = re.compile(
    r"(?:数据库|飞行)?记录\s*(?:的)?\s*id\b|(?<![A-Za-z0-9_])id\s*[:：=]?\s*\d+|"
    r"(?:本次|此次)?(?:查询条件|查询参数)\s*(?:为|是|采用|包括)|"
    r"(?:仅|只)\s*(?:选取|查询|返回)(?:了)?[^。；\n]{0,70}(?:字段|列)|"
    r"(?:调用|使用)[^。；\n]{0,30}(?:工具|函数)|"
    r"(?:SQL|数据库)(?:语句|执行流程|原始返回)",
    re.IGNORECASE,
)
_RAW_STATUS_PATTERN = re.compile(r"(?<![A-Za-z0-9_])(?:normal|warning|danger)(?![A-Za-z0-9_])", re.IGNORECASE)


def user_requests_record_id(question: str) -> bool:
    # 用户明确提到记录编号时才允许将其作为业务编号提供给模型。
    normalized = re.sub(r"\s+", "", question).lower()
    return any(word in normalized for word in ("记录编号", "记录id", "record_id"))


def find_internal_markers(answer: str) -> set[str]:
    # 只匹配具体内部标识和查询痕迹，不因普通的“查询”或“记录”拦截回答。
    markers = set()
    if _INTERNAL_NAME_PATTERN.search(answer):
        markers.add("内部字段或工具名")
    if _SQL_PATTERN.search(answer):
        markers.add("SQL语句")
    if _PARAMETER_PATTERN.search(answer):
        markers.add("查询参数")
    if _PROCESS_PATTERN.search(answer):
        markers.add("查询过程")
    if _RAW_STATUS_PATTERN.search(answer):
        markers.add("原始状态值")
    return markers
