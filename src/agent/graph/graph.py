from langgraph.graph import START,END,StateGraph

from src.agent.graph.graph_state import UAVGraphState
from src.agent.graph.nodes.agent_node import graph_agent_node
from src.agent.graph.nodes.tool_node import graph_tool_node
from src.agent.graph.nodes.summary_node import graph_summary_node
from src.agent.graph.edges.conditional_agent_edge import agent_edge


from langgraph.checkpoint.memory import InMemorySaver


def build_graph(*, embedding_model=None, rerank_model=None, checkpointing=True,
                checkpointer=None):
    graph_builder = StateGraph(UAVGraphState)
    # FastAPI 可传入 PostgreSQL saver；独立演示仍沿用内存检查点。
    saver = checkpointer
    if saver is None and checkpointing:
        saver = InMemorySaver()
    graph_builder.add_node("agent",graph_agent_node)
    def tool_node_with_models(state: UAVGraphState):
        return graph_tool_node(
            state,
            embedding_model=embedding_model,
            rerank_model=rerank_model,
        )

    graph_builder.add_node("tool",tool_node_with_models)
    graph_builder.add_node("summary",graph_summary_node)
    graph_builder.add_edge(START,"summary")
    graph_builder.add_edge("summary","agent")
    graph_builder.add_conditional_edges("agent",agent_edge,{
        "tool":"tool",
        "end":END
    })
    graph_builder.add_edge("tool","agent")
    graph = graph_builder.compile(checkpointer=saver)
    return graph
