from src.agent.graph.graph_state import UAVGraphState
from src.agent.answer_guard import find_internal_markers
from src.llm.llm import agent_ask_llm
from src.llm.prompt.prompt import build_agent_prompt,build_total_prompt
from src.agent.tools.tool_definitions import TOOL_DEFINITIONS
from src.agent.memory.context_manager import select_context_with_budget,summarized_message_turns
from src.agent.memory.context_manager import count_token

import json
import logging

logger = logging.getLogger(__name__)
max_user_prompt_token = 20000
max_total_prompt_token = 50000

_SAFE_ANSWER = {"answer": "暂时无法整理答复，请稍后重试。", "sources": []}


def _read_public_answer(response):
    # 只从合法的最终 JSON 中取用户可见内容，并检查正文和来源是否含内部标识。
    try:
        answer = json.loads(response.output_text)
    except (TypeError, ValueError):
        return None, {"回答格式"}
    if not isinstance(answer, dict) or not isinstance(answer.get("answer"), str):
        return None, {"回答格式"}
    if not isinstance(answer.get("sources"), list):
        return None, {"回答格式"}
    markers = find_internal_markers(answer["answer"])
    for source in answer["sources"]:
        if not isinstance(source, dict) or not isinstance(source.get("title"), str) or not isinstance(source.get("url"), str):
            return None, {"回答格式"}
        markers.update(find_internal_markers(source["title"]))
        markers.update(find_internal_markers(source["url"]))
    return answer, markers


def graph_agent_node(state:UAVGraphState):
    selection = select_context_with_budget(query=state['query'],context=state['context'],message=state['message'],keep_previous_turns=3)
    selected_message = selection["message"]
    total_prompt = build_total_prompt(question=state['query'],context=state['context'],message=selected_message,conversation_summary=state["conversation_summary"])
    user_prompt = build_agent_prompt(question=state['query'],context=state['context'],message=selected_message,conversation_summary=state["conversation_summary"])
    if count_token(user_prompt) > max_user_prompt_token:
        logger.error("用户提示词token超过限制")
        raise ValueError("提示词token超过限制")
    elif count_token(total_prompt) > max_total_prompt_token:
        logger.error("整体提示词超过token预算")
    
    response = agent_ask_llm(prompt=user_prompt,tool_definitions=TOOL_DEFINITIONS)
    for item in response.output:
        if item.type == "function_call":
            logger.info("调用function_call")
            return {
                "current_tool_call":item.model_dump(exclude_none=True),
                "message":[item.model_dump(exclude_none=True)],
                "finished":False
            }
        
    for item in response.output:
        if item.type == "message":
            answer, markers = _read_public_answer(response)
            if markers:
                # 日志只保留命中的类别，不写入可能包含内部信息的原回答。
                logger.warning("回答未通过对外展示检查：%s", ", ".join(sorted(markers)))
                retry_prompt = user_prompt + "\n请只回答用户需要的飞行信息，不描述查询过程或内部实现；只输出规定的最终 JSON。"
                try:
                    retry_response = agent_ask_llm(
                        prompt=retry_prompt,
                        tool_definitions=TOOL_DEFINITIONS,
                        tool_choice="none",
                    )
                    answer, markers = _read_public_answer(retry_response)
                except Exception:
                    logger.exception("重新生成对外答复失败")
                    answer, markers = None, {"重新生成失败"}
                if markers:
                    logger.warning("重新生成的答复仍未通过对外展示检查：%s", ", ".join(sorted(markers)))
                    answer = _SAFE_ANSWER.copy()
            logger.info("提供最终答案")
            return {
                "answer":answer,
                "current_tool_call":None,
                "message":[{
                    "role":"assistant",
                    "content":answer
                }],
                "finished":True
            }
        
    logger.error("LLM没有返回有效的工具调用请求会或信息")
    raise RuntimeError("LLM没有返回有效的工具调用或消息")
