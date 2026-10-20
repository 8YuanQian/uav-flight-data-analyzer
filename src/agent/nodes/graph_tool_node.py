from src.agent.graph_state import UAVGraphState
from src.agent.tools_registry import execute_tool
from src.agent.result_processor import build_model_result,build_error_result_message,prepare_tool_result
from src.agent.context_manager import cheak_tool_result_budget,handle_tool_result_overflow
from src.json_conversion import serialize_tool_result
from src.agent.context_manager import count_token

import json
import logging

logger = logging.getLogger(__name__)

def graph_tool_node(state: UAVGraphState):
    if state["current_tool_call"] is None:
        raise ValueError("没有正确的工具调用参数")

    if state["current_tool_call"]["name"] == "rag_search":
        try:
            tool_result = execute_tool(
                tool_name=state["current_tool_call"]["name"],
                tool_arguments=state["current_tool_call"]["arguments"]
            )
        except Exception:
            logger.exception(
                "工具执行错误,tool_name=%s",
                state["current_tool_call"]["name"]
            )
            return build_error_result_message(
                type="function_call_output",
                call_id=state["current_tool_call"]["call_id"],
                error_code="TOOL_EXECUTION_FAILED",
                message="工具执行错误"
            )

        try:
            result = prepare_tool_result(data=tool_result)

        except TypeError:
            logger.exception("无法JOSN序列化")
            return build_error_result_message(
                type="function_call_output",
                call_id=state["current_tool_call"]["call_id"],
                error_code="TOOL_RESULT_SERIALIZATION_FAILED",
                message="无法JOSN序列化。"
            )

        except ValueError:
            logger.exception("工具结果处理失败，请检查参数和返回数据")
            return build_error_result_message(
                type="function_call_output",
                call_id=state["current_tool_call"]["call_id"],
                error_code="TOOL_RESULT_SERIALIZATION_FAILED",
                message="工具结果处理失败，请检查参数和返回数据。"
            )

        return {
            "context": [result["serialized_result"]],
            "message": [{
                "type": "function_call_output",
                "call_id": state["current_tool_call"]["call_id"],
                "output": result["model_output"]
            }],
            "current_tool_call": None
        }

    elif state["current_tool_call"]["name"] == "analyze_flight_data":
        try:
            tool_result = execute_tool(
                tool_name=state["current_tool_call"]["name"],
                tool_arguments=state["current_tool_call"]["arguments"]
            )
        except Exception:
            logger.exception(
                "工具执行错误,tool_name=%s",
                state["current_tool_call"]["name"]
            )
            return build_error_result_message(
                type="function_call_output",
                call_id=state["current_tool_call"]["call_id"],
                error_code="TOOL_EXECUTION_FAILED",
                message="工具执行错误。"
            )

        try:
            result = prepare_tool_result(data=tool_result)

        except TypeError:
            logger.exception("无法JOSN序列化")
            return build_error_result_message(
                type="function_call_output",
                call_id=state["current_tool_call"]["call_id"],
                error_code="TOOL_RESULT_SERIALIZATION_FAILED",
                message="无法JOSN序列化。"
            )

        except ValueError:
            logger.exception("工具结果处理失败，请检查参数和返回数据")
            return build_error_result_message(
                type="function_call_output",
                call_id=state["current_tool_call"]["call_id"],
                error_code="TOOL_RESULT_SERIALIZATION_FAILED",
                message="工具结果处理失败，请检查参数和返回数据。"
            )

        return {
            "tool_results": [result["serialized_result"]],
            "message": [{
                "type": "function_call_output",
                "call_id": state["current_tool_call"]["call_id"],
                "output": result["model_output"]
            }],
            "current_tool_call": None
        }

    elif state["current_tool_call"]["name"] == "get_flight_data":
        try:
            tool_result = execute_tool(
                tool_name=state["current_tool_call"]["name"],
                tool_arguments=state["current_tool_call"]["arguments"]
            )
        except Exception:
            logger.exception(
                "工具执行错误,tool_name=%s",
                state["current_tool_call"]["name"]
            )
            return build_error_result_message(
                type="function_call_output",
                call_id=state["current_tool_call"]["call_id"],
                error_code="TOOL_EXECUTION_FAILED",
                message="工具执行错误。"
            )

        try:
            arguments = json.loads(
                state["current_tool_call"]["arguments"]
            )

            model_data = build_model_result(
                "get_flight_data",
                tool_result,
                fields=arguments.get("fields")
            )
            result = prepare_tool_result(data=model_data)

        except (TypeError, ValueError):
            logger.exception("飞行数据结果处理失败")

            return build_error_result_message(
                type="function_call_output",
                call_id=state["current_tool_call"]["call_id"],
                error_code="TOOL_RESULT_PROCESSING_FAILED",
                message="飞行数据结果处理失败，请检查参数和返回数据。"
            )

        return {
            "tool_results": [result["serialized_result"]],
            "message": [{
                "type": "function_call_output",
                "call_id": state["current_tool_call"]["call_id"],
                "output": result["model_output"]
            }],
            "current_tool_call": None
        }

    else:
        logger.error(
            "调用了未知工具,tool_name = %s",
            state["current_tool_call"]["name"]
        )
        raise ValueError("未知工具")
