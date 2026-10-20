from src.agent.graph_state import UAVGraphState


def agent_edge(state:UAVGraphState):
    if state["current_tool_call"] is not None and state["finished"] == False:
        return "tool"
    elif state["answer"] != "" and state["current_tool_call"] is None and state["finished"] == True:
        return "end"
    else:
        raise ValueError("agent_edge路由出错")
