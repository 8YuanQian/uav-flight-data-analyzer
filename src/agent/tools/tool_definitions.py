TOOL_DEFINITIONS = [
    {
        "type":"function",
        "name":"get_flight_data",
        "description":"查询新 flight_records 表。可按数据库生成的 record_id 精确查询，或按 uav_code 查询一架飞行器的最近记录；CSV 中用于分组的 flight_id 不入库，不能用它查询。",
        "parameters":{
            "type":"object",
            "properties":{
                "limit":{
                    "type":"integer",
                    "description":"这个参数决定了返回的数据条数,默认值为1"
                },
                "record_id":{
                    "type":"integer",
                    "description":"数据库自动生成的飞行记录 id"
                },
                "uav_code":{
                    "type":"string",
                    "description":"飞行器编号，用于查询该飞行器的记录"
                },
                "fields": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "id",
                            "uav_code",
                            "duration_minutes",
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
                "record_id": {
                    "type": "integer",
                    "description": "数据库自动生成的飞行记录 id"
                },
                "uav_code": {
                    "type": "string",
                    "description": "只分析这架飞行器的最近记录"
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
