from dataclasses import dataclass,field


@dataclass
class UAVAgentState:
    # 当前用户问题
    query: str

    # LLM上下文
    context:list = field(default_factory=list)

    # 当前工具调用
    current_tool_call:dict | None = None

    # 工具执行历史
    tool_results:list = field(default_factory=list)

    # 飞行数据
    flight_data:list = field(default_factory=list)

    # 分析结果
    analysis_result:dict = field(default_factory=dict)

    # 最终回答
    answer:str = ""

    # 是否结束
    finished:bool = False

    def start_new_turn(self,query:str):
        self.query = query
        self.current_tool_call = None
        self.answer = ""
        self.finished = False