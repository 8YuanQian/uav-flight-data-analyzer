from src.agent.loop.state import UAVAgentState
from src.agent.tools.tools_registry import execute_tool
from src.agent.memory.short_term_memory import ConversationMessage

def tool_node(state:UAVAgentState,message:ConversationMessage):
    if state.current_tool_call:
        tool_result = execute_tool(tool_name=state.current_tool_call["tool_name"],tool_arguments=state.current_tool_call["tool_arguments"])
        state.tool_results.append(tool_result)
        state.current_tool_call = None
        return {
            "state":state,
            "message":message
        }
    else:
        return {
            "state":state,
            "message":message
        }
    