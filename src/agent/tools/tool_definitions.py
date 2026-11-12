TOOL_DEFINITIONS = [
    {
        "type":"function",
        "name":"get_flight_data",
        "description":"查询当前用户的飞行记录。可使用用户提供的 flight_id 或系统 record_id 作为起点，二者互斥，不能同时指定；limit 大于 1 时从该记录开始按开始时间和 ID 倒序查询多条，此时不按飞行器筛选。未提供起点时可按飞行器查询最近记录。如果用户提供了id却不能明确判断是record_id还是flight_id就不应该调用这个函数而是要询问用户这个id的具体类型",
        "parameters":{
            "type":"object",
            "properties":{
                "limit":{
                    "type":"integer",
                    "description":"返回记录数量，范围 1 至 100，默认 1；与 record_id 或 flight_id 同时提供且大于 1 时，从该记录开始倒序查询"
                },
                "record_id":{
                    "type":"integer",
                    "description":"数据库自动生成的飞行记录 id；limit 大于 1 时是范围查询的起点。根据用户的查询要求选择，如果用户没有指定 record_id 则不用填写此参数；与 flight_id 互斥，不能同时指定"
                },
                "flight_id":{
                    "type":"string",
                    "description":"用户在 CSV 中提供的飞行编号，在当前用户下唯一且区分大小写；可作为查询或范围查询的起点，与 record_id 互斥，不能同时指定"
                },
                "uav_code":{
                    "type":"string",
                    "description":"飞行器编号，用于查询该飞行器的记录"
                },
                "uav_id":{"type":"integer","description":"当前用户的飞行器系统 ID，只能查询本人飞行器"},
                "fields": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "id",
                            "flight_id",
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
                    "description": "可选的飞行记录字段列表；不传或传空列表时保留全部检索数据，传非空列表时只保留指定字段"
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
            用户提供的 flight_id 与系统 record_id 互斥，不能同时指定。
            使用 flight_id 时，limit 大于 1 会从该记录开始按时间和系统 ID 倒序分析；
            使用 record_id 时仅分析该条记录。指定任一编号时不按飞行器筛选。

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
                        "需要分析的飞行记录数量，范围 1 至 100，默认 1；与 flight_id 同时提供时，从该记录开始倒序分析；record_id 仅分析一条"
                },
                "record_id": {
                    "type": "integer",
                    "description": "数据库自动生成的飞行记录 id，与 flight_id 互斥，不能同时指定"
                },
                "flight_id": {
                    "type": "string",
                    "description": "用户在 CSV 中提供的飞行编号，在当前用户下唯一且区分大小写；与 record_id 互斥，不能同时指定"
                },
                "uav_code": {
                    "type": "string",
                    "description": "只分析这架飞行器的最近记录"
                },
                "uav_id": {"type": "integer", "description": "当前用户的飞行器系统 ID"}
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
