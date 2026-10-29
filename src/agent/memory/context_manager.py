import tiktoken
import json

from src.llm.prompt.prompt import build_agent_prompt

encoding = tiktoken.get_encoding("o200k_base")


def select_message(message, keep_previous_turns: int = 1):
    if keep_previous_turns < 0:
        raise ValueError("历史轮次不能小于0")

    if not message:
        return []

    turns = []
    for item in message:
        if item.get("role") == "user":
            turns.append([item])
        elif turns:
            turns[-1].append(item)

    if not turns:
        return []

    previous_turns = turns[
        max(0, len(turns) - keep_previous_turns - 1):-1
    ]
    result = []
    for turn in previous_turns:
        result.extend(turn)

    # 当前问题由 query 单独提供
    # 保留当前轮已产生的工具交互
    result.extend(turns[-1][1:])
    return result


def count_token(text:str):
    return len(encoding.encode(text))


def select_context_with_budget(query,message,context,conversation_summary=None,max_token=1000,keep_previous_turns=3):
    for turns in range(keep_previous_turns,-1,-1):
        result = select_message(message=message,keep_previous_turns=turns)
        prompt = build_agent_prompt(question=query,message=result,context=context,conversation_summary=conversation_summary)
        token = count_token(prompt)
        if token > max_token:
            continue
        else:
            return {
                "message":result,
                "token_count":token,
                "select_turns":turns
            }
    raise ValueError("当前任务的必要上下文已超过预算")


def check_tool_result_budget(tool_result,max_token:int=1000)->dict:
    if max_token <= 0:
        raise ValueError("max_token必须大于0")
    
    token = count_token(tool_result)
    print(token)
    return {
        "within_budget":token < max_token,
        "token_count":token,
        "max_token":max_token
    }

    
def handle_tool_result_overflow(token_count:int,max_token:int)->dict:
    return {
        "status": "token_budget_exceeded",
        "required_tokens": token_count,
        "max_tokens": max_token,
        "message": "工具结果超出预算，完整数据未提供给模型，需要采用其他处理方式"
    }


def select_messages_for_summary(message:list[dict],summary_cursor:int,keep_previous_turns:int = 3) -> dict:
    if summary_cursor < 0 or keep_previous_turns < 0:
        raise ValueError("参数不能小于0")

    message_turns = []

    # 1. 按用户轮次分组
    for item in message:
        if item.get("role") == "user":
            message_turns.append([item])
        elif message_turns:
            message_turns[-1].append(item)

    if summary_cursor > len(message_turns):
        raise ValueError("summary_cursor超出轮次范围")

    # 2. 计算能够摘要的轮次数量
    cutoff = max(0,len(message_turns) - keep_previous_turns - 1)

    # 3. 增量选择尚未摘要的完整轮次
    turns_to_summarize = message_turns[
        summary_cursor:cutoff
    ]

    # 4. 展平为消息列表
    messages_to_summarize = [
        item
        for turn in turns_to_summarize
        for item in turn
    ]

    return {
        "messages_to_summarize": messages_to_summarize,
        "new_cursor": max(summary_cursor, cutoff)
    }


def summarized_message_turns(message:list[dict],summary_cursor:int,keep_previous_turns:int = 2) -> dict:
    if summary_cursor < 0 or keep_previous_turns < 0:
        raise ValueError("参数不能小于0")

    message_turns = []

    # 1. 按用户轮次分组
    for item in message:
        if item.get("role") == "user":
            message_turns.append([item])
        elif message_turns:
            message_turns[-1].append(item)

    if summary_cursor > len(message_turns):
        raise ValueError("summary_cursor超出轮次范围")

    # 2. 计算能够摘要的轮次数量
    cutoff = max(0,len(message_turns) - keep_previous_turns - 1)
    return cutoff
