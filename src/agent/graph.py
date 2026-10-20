from langgraph.graph import START,END,StateGraph

from src.agent.graph_state import UAVGraphState
from src.agent.nodes.graph_agent_node import graph_agent_node
from src.agent.nodes.graph_tool_node import graph_tool_node
from src.agent.edges.conditional_agent_edge import agent_edge


from langgraph.checkpoint.memory import InMemorySaver


def graph_work():
    graph_builder = StateGraph(UAVGraphState)
    graph_builder.add_node("agent",graph_agent_node)
    graph_builder.add_node("tool",graph_tool_node)
    graph_builder.add_edge(START,"agent")
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


def build_graph():
    graph_builder = StateGraph(UAVGraphState)
    checkpointer = InMemorySaver()
    graph_builder.add_node("agent",graph_agent_node)
    graph_builder.add_node("tool",graph_tool_node)
    graph_builder.add_edge(START,"agent")
    graph_builder.add_conditional_edges("agent",agent_edge,{
        "tool":"tool",
        "end":END
    })
    graph_builder.add_edge("tool","agent")
    graph = graph_builder.compile(checkpointer=checkpointer)
    return graph



if __name__ == "__main__":
    graph_work()

