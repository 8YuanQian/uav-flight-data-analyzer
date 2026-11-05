from langgraph.graph import START,END,StateGraph

from src.agent.graph.graph_state import UAVGraphState
from src.agent.graph.nodes.agent_node import graph_agent_node
from src.agent.graph.nodes.tool_node import graph_tool_node
from src.agent.graph.nodes.summary_node import graph_summary_node
from src.agent.graph.edges.conditional_agent_edge import agent_edge


from langgraph.checkpoint.memory import InMemorySaver


def graph_work():
    graph_builder = StateGraph(UAVGraphState)
    graph_builder.add_node("agent",graph_agent_node)
    graph_builder.add_node("tool",graph_tool_node)
    graph_builder.add_node("summary",graph_summary_node)
    graph_builder.add_edge(START,"summary")
    graph_builder.add_edge("summary","agent")
    graph_builder.add_conditional_edges("agent",agent_edge,{
        "tool":"tool",
        "end":END
    })
    graph_builder.add_edge("tool","agent")
    graph = graph_builder.compile()
    #print(graph.get_graph().draw_ascii())
    query = "查询最近一次飞行记录"
    initial_state = {
        "query":query,
        "context":[],
        "message":[{
            "role":"user",
            "content":query
        }],
        "current_tool_call":None,
        "tool_results":[],
        "answer":"",
        "finished":False
    }
    for event in graph.stream(
        initial_state,
        stream_mode="updates",
        config={"recursion_limit": 10}
    ):
        for node_name, update in event.items():
            if node_name == "agent":
                print("执行节点:agent")
                tool_call = update.get("current_tool_call")

                if tool_call:
                    print("请求工具:", tool_call["name"])

                print("finished:", update.get("finished"))
                print()

            if node_name == "tool":
                print("执行节点: tool")
                if "tool_results" in update:
                    print("工具结果数量:", len(update["tool_results"]))

                if "context" in update:
                    print("RAG上下文数量:", len(update["context"]))
                print()


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



if __name__ == "__main__":
    graph_work()

