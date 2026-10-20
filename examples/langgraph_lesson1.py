from typing import TypedDict
from langgraph.graph import START,END,StateGraph

class State(TypedDict):
    query:str
    current_tool:str|None
    tool_result:str
    answer:str
    finished:bool

def main():
    graph_builder = StateGraph(State)
    graph_builder.add_node("agent",agent_node)
    graph_builder.add_node("tool",tool_node)
    graph_builder.add_edge(START,"agent")
    graph_builder.add_conditional_edges(
        "agent",
        route_agent,
        {
            "end":END,
            "tool":"tool"
        }
    )
    graph_builder.add_edge("tool","agent")
    graph = graph_builder.compile()
    result = graph.invoke({
        "query":"查找最近一次的飞行数据",
        "current_tool":None,
        "tool_result":"",
        "answer":"",
        "finished":False
    })
    print(result["answer"])
    print(result["finished"])


def agent_node(state:State):
    print("执行agent_node")
    current_tool = ""

    if "查找" in state["query"] and state["tool_result"] == "":
        current_tool = "tool"
    else:
        return {
            "answer":"任务完成",
            "finished":True
        }
    
    return {
        "current_tool":current_tool
    }


def tool_node(state:State):
    if state["current_tool"] is None:
        return
    
    print("执行tool_node")
    tool_result = "已执行工具"
    return {
        "current_tool":None,
        "tool_result":tool_result,
    }

def route_agent(state):
    if state["current_tool"] is None and state["finished"] == True:
        return "end"
    else:
        return "tool"



if __name__ == "__main__":
    main()   