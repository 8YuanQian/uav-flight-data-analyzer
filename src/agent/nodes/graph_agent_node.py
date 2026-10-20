from src.agent.graph_state import UAVGraphState
from src.llm import agent_ask_llm
from src.prompt import build_agent_prompt
from src.agent.tool_difinitions import TOOLS_DEFINITIONS
from src.agent.context_manager import select_context_with_budget

import json


def graph_agent_node(state:UAVGraphState):
    selection = select_context_with_budget(query=state['query'],context=state['context'],message=state['message'])
    selected_message = selection["message"]
    prompt = build_agent_prompt(question=state['query'],context=state['context'],message=selected_message)
    response = agent_ask_llm(prompt=prompt,tools_difinitions=TOOLS_DEFINITIONS)
    for item in response.output:
        if item.type == "function_call":
            return {
                "current_tool_call":item.model_dump(exclude_none=True),
                "message":[item.model_dump(exclude_none=True)],
                "finished":False
            }
        
    for item in response.output:
        if item.type == "message":
            return {
                "answer":json.loads(response.output_text),
                "current_tool_call":None,
                "message":[{
                    "role":"assistant",
                    "content":json.loads(response.output_text)
                }],
                "finished":True
            }

    raise RuntimeError("LLM没有返回有效的工具调用或消息")