import json
import logging
from fastapi import HTTPException

from src.agent.graph.graph_state import UAVGraphState
from src.agent.result_processor import build_error_result_message
from src.agent.tools.tool_definitions import TOOL_DEFINITIONS
from src.auth.data_scope import require_data_user_id, require_data_user_jwt
from src.auth.security import InvalidAccessToken, read_access_token
from src.database.connection import get_connection

logger = logging.getLogger(__name__)

TOOL_NAME = frozenset(("get_flight_data", "analyze_flight_data", "rag_search"))
_FLIGHT_ARGUMENTS = frozenset(("limit", "record_id", "flight_id", "uav_code", "uav_id"))
_TOOL_ARGUMENTS = {
    "get_flight_data": _FLIGHT_ARGUMENTS | {"fields"},
    "analyze_flight_data": _FLIGHT_ARGUMENTS,
    "rag_search": frozenset(("query",)),
}
_MAX_DATABASE_ID = 2**63 - 1
# 同一轮累计三次参数校验失败后结束；成功校验不会清零。
MAX_SECURITY_FAILURES = 3
_FAILURE_LIMIT_ANSWER = "本次查询多次未能通过参数校验，请调整问题后重试。"


def _error(state: UAVGraphState, call_id: str, code: str, message: str) -> dict:
    # 参数错误允许模型修正；计数直接覆盖旧值，不能使用累加型状态字段。
    failure_count = state.get("security_failure_count", 0) + 1
    update = build_error_result_message(
        type="function_call_output", call_id=call_id,
        error_code=code, message=message,
    )
    update["security_failure_count"] = failure_count
    if failure_count >= MAX_SECURITY_FAILURES:
        answer = {"answer": _FAILURE_LIMIT_ANSWER, "sources": []}
        update["answer"] = answer
        update["finished"] = True
        # 保留对应的工具失败结果，再保存固定答复，使续聊历史中的调用成对闭合。
        update["message"].append({"role": "assistant", "content": answer})
        logger.warning("本轮参数校验失败达到上限：%s", failure_count)
    return update


def _parse_arguments(tool_name: str, raw_arguments) -> dict:
    # 工具参数通常是 JSON 字符串，先解析再按工具分别校验。
    if isinstance(raw_arguments, str):
        try:
            arguments = json.loads(raw_arguments)
        except (ValueError, TypeError) as exc:
            raise ValueError("工具参数不是有效的 JSON 对象") from exc
    elif isinstance(raw_arguments, dict):
        arguments = raw_arguments
    else:
        raise ValueError("工具参数必须是 JSON 对象")
    if not isinstance(arguments, dict):
        raise ValueError("工具参数必须是 JSON 对象")
    if any(not isinstance(key, str) for key in arguments):
        raise ValueError("工具参数名称必须是字符串")
    if set(arguments) - _TOOL_ARGUMENTS[tool_name]:
        raise ValueError("提供了工具不支持的参数")
    result = dict(arguments)

    if tool_name == "rag_search":
        query = result.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("查询内容不能为空")
        return result

    # 不接受布尔值和数字字符串冒充整数；缺少 limit 时明确提供默认值。
    limit = result.get("limit")
    if limit is None:
        result["limit"] = 1
    elif type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit 必须是 1 到 100 之间的整数")
    for name in ("record_id", "uav_id"):
        value = result.get(name)
        if value is not None and (type(value) is not int or not 1 <= value <= _MAX_DATABASE_ID):
            raise ValueError(f"{name} 必须是有效的正整数")
    for name in ("flight_id", "uav_code"):
        value = result.get(name)
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} 必须是非空字符串")
            result[name] = value.strip()
    if result.get("uav_code") is not None:
        result["uav_code"] = result["uav_code"].upper()
    if result.get("record_id") is not None and result.get("flight_id") is not None:
        raise ValueError("flight_id 和 record_id 不能同时指定")

    if tool_name == "get_flight_data" and result.get("fields") is not None:
        definition = next(item for item in TOOL_DEFINITIONS if item["name"] == "get_flight_data")
        allowed = set(definition["parameters"]["properties"]["fields"]["items"]["enum"])
        fields = result["fields"]
        if not isinstance(fields, list) or any(
            not isinstance(field, str) or field not in allowed for field in fields
        ):
            raise ValueError("fields 必须是工具允许的字段列表")
    return result


def _resources_belong_to_user(user_id: int, arguments: dict) -> bool:
    # 只预查明确指定的资源；真正执行查询时仓储层仍保留用户归属条件。
    record_id = arguments.get("record_id")
    flight_id = arguments.get("flight_id")
    uav_id = arguments.get("uav_id")
    uav_code = arguments.get("uav_code")
    if all(value is None for value in (record_id, flight_id, uav_id, uav_code)):
        return True

    with get_connection() as conn:
        with conn.cursor() as cursor:
            if record_id is not None or flight_id is not None:
                if record_id is not None:
                    condition, identifier = "flight.id = %s", record_id
                else:
                    condition, identifier = "flight.flight_id = %s", flight_id
                cursor.execute(
                    "SELECT 1 FROM flight_records AS flight "
                    "JOIN uavs AS uav ON uav.id = flight.uav_id "
                    f"WHERE flight.user_id = %s AND uav.user_id = %s AND {condition} LIMIT 1",
                    (user_id, user_id, identifier),
                )
                if cursor.fetchone() is None:
                    return False

            if uav_id is not None or uav_code is not None:
                conditions = ["user_id = %s"]
                params = [user_id]
                if uav_id is not None:
                    conditions.append("id = %s")
                    params.append(uav_id)
                if uav_code is not None:
                    conditions.append("uav_code = %s")
                    params.append(uav_code)
                cursor.execute(
                    "SELECT 1 FROM uavs WHERE " + " AND ".join(conditions) + " LIMIT 1",
                    tuple(params),
                )
                if cursor.fetchone() is None:
                    return False
    return True


def graph_security_node(state: UAVGraphState) -> dict:
    # 节点只接收状态；身份和 JWT 从同一个请求作用域读取，不进入持久化状态。
    try:
        current_user_id = require_data_user_id()
        jwt_token = require_data_user_jwt()
    except PermissionError as exc:
        raise HTTPException(
            status_code=401, detail="请先登录", headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    try:
        identity = read_access_token(jwt_token)
    except InvalidAccessToken as exc:
        raise HTTPException(
            status_code=401, detail="登录已失效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except RuntimeError as exc:
        logger.error("登录验证配置不可用")
        raise HTTPException(status_code=503, detail="身份验证暂时不可用") from exc
    if current_user_id != identity.user_id:
        raise HTTPException(
            status_code=401, detail="用户身份不匹配，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    tool_call = state.get("current_tool_call")
    if not isinstance(tool_call, dict):
        raise ValueError("没有有效的工具调用")
    call_id = tool_call.get("call_id")
    if not isinstance(call_id, str) or not call_id.strip():
        raise ValueError("工具调用缺少 call_id")

    tool_name = tool_call.get("name")
    if not isinstance(tool_name, str) or tool_name not in TOOL_NAME:
        return _error(state, call_id, "TOOL_ARGUMENTS_INVALID", "提供了未知的工具名")
    try:
        arguments = _parse_arguments(tool_name, tool_call.get("arguments"))
    except ValueError as exc:
        return _error(state, call_id, "TOOL_ARGUMENTS_INVALID", str(exc))

    # RAG 当前使用共享知识库，只校验登录和参数，不伪造文档归属限制。
    if tool_name != "rag_search":
        try:
            belongs_to_user = _resources_belong_to_user(identity.user_id, arguments)
        except Exception as exc:
            logger.error("无法核验数据归属")
            raise HTTPException(status_code=503, detail="暂时无法核验数据归属") from exc
        # 权限错误直接退出 Graph；不向模型返回可重试的工具错误。
        if not belongs_to_user:
            raise HTTPException(status_code=403, detail="数据不存在或无权访问")

    # 成功时交给工具节点；参数错误回到 Agent，达到失败上限则直接结束。
    # 业务参数校验结束后才注入已验证身份，模型无权提供或覆盖这个字段。
    arguments["user_id"] = identity.user_id
    verified_call = dict(tool_call)
    verified_call["arguments"] = json.dumps(arguments, ensure_ascii=False)
    return {"current_tool_call": verified_call}

