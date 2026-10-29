from src.agent.tools.get_flight_data import get_flight_data
from src.agent.tools.analyze_flight_data import analyze_flight_data
from src.agent.tools.rag_search import rag_search

import json


def execute_tool(tool_name,tool_arguments, *, embedding_model=None, rerank_model=None):
    arguments = json.loads(tool_arguments)
    if tool_name == "get_flight_data":
        return get_flight_data(
            limit=arguments.get("limit") or 1,
            record_id=arguments.get("record_id"),
            uav_code=arguments.get("uav_code"),
        )
    elif tool_name == "analyze_flight_data":    
        return analyze_flight_data(
            record_id=arguments.get("record_id"),
            uav_code=arguments.get("uav_code"),
            limit=arguments.get("limit") or 1,
        )
    elif tool_name == "rag_search":
        return rag_search(
            query=arguments.get("query"),
            embedding_model=embedding_model,
            rerank_model=rerank_model,
        )
    else:
        raise ValueError("未知工具")
