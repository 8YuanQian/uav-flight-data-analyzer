from openai import OpenAI,APIConnectionError
import os
import json

from tools.flights_tools import get_latest_flight_analysis,get_flight_analysis_by_id

tools_definitions = [
    {
        "type":"function",
        "name":"get_latest_flight_analysis",
        "description":"这个函数能够帮你获得最近的一次分析数据,其中包含了查询的状态,这条数据的id,文件名,数据行数,最高速度,最高温度,最低电量",
        "parameters":{
            "type":"object",
            "properties":{},
            "required":[],
            "additionalProperties":False
        }
    },
    {
        "type":"function",
        "name":"get_flight_analysis_by_id",
        "description":"这个函数能够根据参数索引对应id的数据库数据",
        "parameters":{
            "type":"object",
            "properties":{
                "id":{
                    "type":"integer",
                    "description":"这个工具会根据这个参数的值索引对应id的数据库数据"
                }
            },
            "required":["id"],
            "additionalProperties":False
        }
    }
]

def answer_flight_question(question):

    api_key = os.getenv("DEEPSEEK_API_KEY") 
    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com"
    )

    instructions = "你是一名无人机数据分析师，无人机的数据由Python程序进行计算，你负责整合分析数据。未提供的数据不允许猜测或编造。可以使用我提供的工具以获取你需要的数据。用户明确要求查询指定分析编号，但没有提供编号时，先询问编号，不得自行改查最新记录。用户要求查询最近或最新记录时，使用最近记录工具，无需提供编号。"
    user_input = question
    input_item = [{"role":"user","content":user_input}]
    has_tools_call = False

    response = client.responses.create(
        model="deepseek-flash",
        instructions=instructions,
        input=input_item,
        tools = tools_definitions,
        tool_choice="auto",
        reasoning={"effort":"none"}
    )

    for i in response.output:
        input_item.append(i.model_dump(exclude_none=True))
        if i.type == "function_call":
            if i.call_id is not None:
                has_tools_call = True
                call_name = i.name
                call_arguments = i.arguments
                call_id = i.call_id
                print(i.name)
                print(i.arguments)
                print(i.call_id)

                if call_name == "get_latest_flight_analysis":
                    if json.loads(call_arguments) != {}:
                        raise ValueError("This function not need arguments")
                    
                    data = get_latest_flight_analysis()
                    print({'status':data['status']})
                elif call_name == "get_flight_analysis_by_id":
                    arguments = json.loads(call_arguments)
                    if type(arguments) != dict or set(arguments) != {"id"}:
                        raise ValueError("argument value error")
                    
                    data = get_flight_analysis_by_id(arguments["id"])
                    print({'status':data['status']})
                else:
                    raise ValueError("未知工具")
                

                input_item.append({
                    "type":"function_call_output",
                    "call_id":call_id,
                    "output":json.dumps(
                        data,
                        ensure_ascii=False,
                        allow_nan=False
                    )
                })

    if has_tools_call == True:
        final_response = client.responses.create(
            model="deepseek-flash",
            instructions=instructions,
            input=input_item,
            tools=tools_definitions,
            tool_choice="none",
            reasoning={"effort":"none"}
        )
        print(f"Final response: {final_response.output_text}")
        return final_response.output_text
    else:
        print(f"Final response: {response.output_text}")
        return response.output_text




