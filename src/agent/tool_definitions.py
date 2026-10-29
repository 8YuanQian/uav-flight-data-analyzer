TOOL_DEFINITIONS = [
    {
        "type":"function",
        "name":"get_flight_data",
        "description":"查询PostgreSQL数据库中的无人机飞行记录。当用户询问最近一次飞行数据、历史飞行记录、飞行状态且不需要进行数据分析时必须调用此工具。(这个工具只返回原始数据) 具体SQL语句如下:'SELECT * FROM flight_records WHERE created_at >= (SELECT MIN(created_at) FROM flight_records WHERE flight_id = %s) ORDER BY created_at DESC LIMIT %s',(flight_id,limit)",
        "parameters":{
            "type":"object",
            "properties":{
                "limit":{
                    "type":"integer",
                    "description":"这个参数决定了返回的数据条数,默认值为1"
                },
                "flight_id":{
                    "type":"string",
                    "description":"这个参数决定了索引的第一条数据的flight_id，后续数据的创建时间都不会大于这个flight_id的创建时间，默认值为SIM-FLIGHT-0001"
                },
                "fields": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "flight_id",
                            "drone_id",
                            "average_speed",
                            "max_speed",
                            "average_height",
                            "max_height",
                            "battery_start",
                            "battery_end",
                            "anomaly_status"
                        ]
                    },
                    "description": "需要展示的飞行记录字段，根据用户问题选择"
                }
            },
            "required":[],
            "additionalProperties":False
        }
    },
    {
        "type": "function",
        "name": "analyze_flight_data",
        "description":
            """
            对无人机飞行数据进行分析。
            工具会自动从数据库获取飞行记录，
            并计算电池消耗、高度、速度、温度等指标，
            判断飞行任务是否存在异常风险。

            当用户需要：
            - 分析最近一次飞行
            - 判断飞行是否异常
            - 查看飞行风险
            - 分析无人机性能
            时必须调用该工具。
            """,
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description":
                        "需要分析的飞行记录数量，默认分析最近1条记录"
                },
                "flight_id": {
                    "type": "string",
                    "description":
                        "指定需要分析的飞行任务ID，例如 SIM-FLIGHT-0001。如果不指定，则分析最近的飞行记录"
                }
            },
            "required": [],
            "additionalProperties": False
        }
    },
    {
        "type":"function",
        "name":"rag_search",
        "description":"这个函数能够根据问题对知识库进行检索，并输出对应知识文档。在用户提问无人机相关知识问题时必须调用这个工具",
        "parameters":{
            "type":"object",
            "properties":{
                "query":{
                    "type":"string",
                    "description":"将用户的问题作为输入，进行RAG检索。"
                }
            },
            "required":["query"],
            "additionalProperties":False
        }
    }
]