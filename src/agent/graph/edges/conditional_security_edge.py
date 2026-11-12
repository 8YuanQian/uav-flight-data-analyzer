from src.agent.graph.graph_state import UAVGraphState

def security_edge(state: UAVGraphState):
    # 安全节点给出固定答复时直接结束，避免再次进入 Agent 调用模型。
    if state.get("finished", False):
        return "end"
    if state["current_tool_call"] is None:
        return "agent"
    return "tool"
