from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver


class DemoState(TypedDict):
    query: str
    history: list[str]
    turn_count: int


def record_node(state: DemoState):
    return {
        "history": [
            *state["history"],
            state["query"]
        ],
        "turn_count": state["turn_count"] + 1
    }


def main():
    builder = StateGraph(DemoState)

    builder.add_node("record", record_node)
    builder.add_edge(START, "record")
    builder.add_edge("record", END)

    checkpointer = InMemorySaver()
    graph = builder.compile(checkpointer=checkpointer)

    config = {
        "configurable": {
            "thread_id": "demo_001"
        }
    }

    # 第一轮
    result1 = graph.invoke(
        {
            "query": "查询最近一次飞行",
            "history": [],
            "turn_count": 0
        },
        config=config
    )

    print("第一轮:", result1)

    # 第二轮：只更新新问题
    result2 = graph.invoke(
        {
            "query": "分析刚才那次飞行"
        },
        config=config
    )

    print("第二轮:", result2)

    # 查看保存的状态
    snapshot = graph.get_state(config)

    print("保存的状态:", snapshot.values)
    print("等待执行的节点:", snapshot.next)


if __name__ == "__main__":
    main()
