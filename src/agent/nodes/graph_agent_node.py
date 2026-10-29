from src.agent.graph_state import UAVGraphState
from src.llm import agent_ask_llm
from src.prompt import build_agent_prompt,build_total_prompt
from src.agent.tool_definitions import TOOL_DEFINITIONS
from src.agent.context_manager import select_context_with_budget,summarized_message_turns
from src.agent.context_manager import count_token

import json
import logging

logger = logging.getLogger(__name__)
max_user_prompt_token = 20000
max_total_prompt_token = 50000

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
            logger.info("提供最终答案")
            return {
                "answer":json.loads(response.output_text),
                "current_tool_call":None,
                "message":[{
                    "role":"assistant",
                    "content":json.loads(response.output_text)
                }],
                "finished":True
            }
        
    logger.error("LLM没有返回有效的工具调用请求会或信息")
    raise RuntimeError("LLM没有返回有效的工具调用或消息")