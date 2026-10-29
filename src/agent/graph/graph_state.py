from typing import TypedDict, Any, Annotated
import operator


class UAVGraphState(TypedDict):
    query: str

    # 当前任务上下文
    context: Annotated[list[Any],operator.add]

    # 消息历史
    message: Annotated[list[dict[str, Any]],operator.add]

    # 当前待执行的工具
    current_tool_call: dict[str, str] | None

    # 工具结果，独立于history
    tool_results: Annotated[list[Any],operator.add]

    # 对话摘要
    conversation_summary: str

    # 下一条尚未摘要消息轮次的索引
    summary_cursor: int 

    # 最终答案
    answer: str

    # 任务状态
    finished: bool
