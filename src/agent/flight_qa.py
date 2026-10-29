import json
import os

from openai import OpenAI

from src.agent.tools.get_latest_flight_analysis import get_latest_flight_analysis
from src.agent.tools.get_flight_analysis_by_id import get_flight_analysis_by_id

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "name": "get_latest_flight_analysis",
        "description": "查询新 flight_records 表中的最近一次飞行，返回数据库生成的记录 id、飞行器编号和汇总信息。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_flight_analysis_by_id",
        "description": "根据数据库生成的飞行记录 id 查询新表；CSV 分组编号不入库，不能用于查询。",
        "parameters": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "integer",
                    "description": "这个工具会根据这个参数的值索引对应id的数据库数据",
                },
            },
            "required": ["id"],
            "additionalProperties": False,
        },
    },
]


def execute_flight_tool(tool_name, arguments_json):
    """解析模型返回的 JSON 参数，执行对应的飞行记录查询工具。"""
    if tool_name == "get_latest_flight_analysis":
        arguments = json.loads(arguments_json)
        if arguments != {}:
            raise ValueError("This function not need arguments")
        return get_latest_flight_analysis()

    if tool_name == "get_flight_analysis_by_id":
        arguments = json.loads(arguments_json)
        if type(arguments) != dict or set(arguments) != {"id"}:
            raise ValueError("argument value error")
        return get_flight_analysis_by_id(arguments["id"])

    raise ValueError("未知工具")


def answer_flight_question(question):
    """接收问题，根据需要查询飞行记录，再生成回答。"""

    api_key = os.getenv("DEEPSEEK_API_KEY")
    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",
    )

    instructions = "你是一名无人机数据分析师，无人机的数据由Python程序进行计算，你负责整合分析数据。未提供的数据不允许猜测或编造。可以使用我提供的工具以获取你需要的数据。用户明确要求查询指定数据库记录 id，但没有提供 id 时，先询问，不得自行改查最新记录。CSV 分组 flight_id 不入库，不能用它查询。用户要求查询最近或最新记录时，使用最近记录工具，无需提供编号。"
    input_items = [{"role": "user", "content": question}]
    has_tool_calls = False

    response = client.responses.create(
        model="deepseek-flash",
        instructions=instructions,
        input=input_items,
        tools=TOOL_DEFINITIONS,
        tool_choice="auto",
        reasoning={"effort": "none"},
    )

    for output_item in response.output:
        input_items.append(output_item.model_dump(exclude_none=True))
        if output_item.type == "function_call" and output_item.call_id is not None:
            has_tool_calls = True
            print(output_item.name)
            print(output_item.arguments)
            print(output_item.call_id)

            tool_result = execute_flight_tool(output_item.name, output_item.arguments)
            print({"status": tool_result["status"]})

            input_items.append({
                "type": "function_call_output",
                "call_id": output_item.call_id,
                "output": json.dumps(
                    tool_result,
                    ensure_ascii=False,
                    allow_nan=False,
                ),
            })

    if has_tool_calls:
        final_response = client.responses.create(
            model="deepseek-flash",
            instructions=instructions,
            input=input_items,
            tools=TOOL_DEFINITIONS,
            tool_choice="none",
            reasoning={"effort": "none"},
        )
        print(f"Final response: {final_response.output_text}")
        return final_response.output_text
    else:
        print(f"Final response: {response.output_text}")
        return response.output_text

