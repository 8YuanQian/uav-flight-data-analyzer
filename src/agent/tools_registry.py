from src.agent.tools import get_flight_data,analyze_flight_data,rag_search

import json


def execute_tool(tool_name,tool_arguments):
    arguments = json.loads(tool_arguments)
    if tool_name == "get_flight_data":
        return get_flight_data(limit=arguments.get("limit"),flight_id=arguments.get("flight_id"))
    elif tool_name == "analyze_flight_data":    
        return analyze_flight_data(flight_id=arguments.get("flight_id"),limit=arguments.get("limit"))
    elif tool_name == "rag_search":
        return rag_search(query=arguments.get("query"))
    else:
        raise ValueError("未知工具")