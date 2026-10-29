from src.rag.evaluation import evaluation_retrieval_rerank,evaluation_retrieval_without_rerank
from src.rag.rag import UAVAssistant
from src.agent.loop.agent import UAVAgent
from src.agent.loop.state import UAVAgentState
from src.agent.memory.short_term_memory import ConversationMessage
from src.agent.loop.nodes.agent_node import agent_node
from src.agent.loop.nodes.tool_node import tool_node
from src.agent.graph.graph import build_graph
from src.agent.memory.context_manager import select_message,count_token,select_context_with_budget
from src.agent.result_processor import project_flight_records,build_model_result




def main():
    # agent = UAVAgent()
    # while True:
    #     query = input("question: ")
    #     answer = agent.work(query=query)
    #     if answer is None:
    #         break

    graph = build_graph()
    query = "查询最近 10 条无人机飞行记录，只展示飞行 ID 和剩余电量。"
    initial_state = {
        "query":query,
        "context":[],
        "message":[{
            "role":"user",
            "content":query
        }],
        "current_tool_call":None,
        "tool_results":[],
        "conversation_summary":"",
        "summary_cursor":0,
        "answer":"",
        "finished":False
    }
    config = {
        "configurable":{
            "thread_id":"uav_session_001"
        }
    }
    result1 = graph.invoke(
        initial_state,
        config=config
    )
    snapshot1 = graph.get_state(config=config)
    state = snapshot1.values
    print(state["answer"]["answer"])
    # print(f"message:{state['message']}")

    # print("当前问题:", state["query"])
    # print("任务完成:", state["finished"])
    # print("工具结果数量:", len(state["tool_results"]))
    # print("用户问题历史:")
    # for item in state["message"]:
    #     if item.get("role") == "user":
    #         print("-", item["content"])

    # print("调用过的工具:")
    # for item in state["message"]:
    #     if item.get("type") == "function_call":
    #         print("-", item["name"])

    # print("等待执行的节点:", snapshot1.next)
    # result2 = graph.invoke(
    #     {
    #         "query":"分析刚刚查到的飞行数据",
    #         "message":[{
    #             "role":"user",
    #             "content":"分析刚刚查到的飞行数据"
    #         }],
    #         "current_tool_call":None,
    #         "answer":"",
    #         "finished":False
    #     },
    #     config=config
    # )
    # snapshot2 = graph.get_state(config=config)
    # state = snapshot2.values

    # print("当前问题:", state["query"])
    # print("任务完成:", state["finished"])
    # print("工具结果数量:", len(state["tool_results"]))
    # print("用户问题历史:")
    # for item in state["message"]:
    #     if item.get("role") == "user":
    #         print("-", item["content"])

    # print("调用过的工具:")
    # for item in state["message"]:
    #     if item.get("type") == "function_call":
    #         print("-", item["name"])

    # print("等待执行的节点:", snapshot2.next)

    # messages = [
    #     {"role": "user", "content": "查询飞行数据"},
    #     {
    #         "type": "function_call",
    #         "name": "get_flight_data",
    #         "call_id": "call_001"
    #     },
    #     {
    #         "type": "function_call_output",
    #         "call_id": "call_001",
    #         "output": "飞行记录"
    #     },
    #     {"role": "assistant", "content": "查询完成"},
    #     {"role": "user", "content": "重新查询飞行数据"},
    #     {
    #         "type": "function_call",
    #         "name": "get_flight_data",
    #         "call_id": "call_002"
    #     },
    #     {
    #         "type": "function_call_output",
    #         "call_id": "call_002",
    #         "output": "飞行记录"
    #     },
    #     {"role": "assistant", "content": "查询完成"},
    #     {"role": "user", "content": "分析这次飞行"}
    # ]

    # print(count_token("你好"))
    # print(count_token("hello"))
    # print()
    # print(
    #     select_context_with_budget(query="How is the weather today?",message=messages)
    # )




if __name__ == "__main__":
    main()
