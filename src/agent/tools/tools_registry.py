from src.agent.tools.get_flight_data import get_flight_data
from src.agent.tools.analyze_flight_data import analyze_flight_data
from src.agent.tools.rag_search import rag_search

import json


def execute_tool(tool_name,tool_arguments, *, user_id: int, embedding_model=None, rerank_model=None):
    # 执行身份由安全节点或可信调用入口提供，不能从模型的业务参数中提取。
    if type(user_id) is not int or user_id <= 0:
        raise ValueError("user_id 必须是正整数")
    arguments = json.loads(tool_arguments)
    if tool_name == "get_flight_data":
        return get_flight_data(
            user_id=user_id,
            limit=arguments.get("limit") or 1,
            record_id=arguments.get("record_id"),
            flight_id=arguments.get("flight_id"),
            uav_code=arguments.get("uav_code"),
            uav_id=arguments.get("uav_id"),
        )
    elif tool_name == "analyze_flight_data":    
        return analyze_flight_data(
            user_id=user_id,
            record_id=arguments.get("record_id"),
            flight_id=arguments.get("flight_id"),
            uav_code=arguments.get("uav_code"),
            uav_id=arguments.get("uav_id"),
            limit=arguments.get("limit"),
        )
    elif tool_name == "rag_search":
        return rag_search(
            query=arguments.get("query"),
            embedding_model=embedding_model,
            rerank_model=rerank_model,
        )
    else:
        raise ValueError("未知工具")
