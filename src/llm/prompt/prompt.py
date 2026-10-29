from src.llm.prompt.instructions import AGENT_SYSTEM_PROMPT
from src.agent.tools.tool_definitions import TOOL_DEFINITIONS



def build_prompt(information,question):
    prompt = f"""
    资料:{information}

    问题:{question}

    请根据资料回答
    """
    return prompt

def build_agent_prompt(question,memory=None,context=None,tool_result=None,conversation_summary=None,message=None):
    prompt = f"""
    问题:{question}

    RAG检索资料:{context}

    消息历史:{message}

    工具调用结果:{tool_result}

    消息历史摘要:{conversation_summary}
    """
    return prompt


def build_total_prompt(question,memory=None,context=None,tool_result=None,conversation_summary=None,message=None):
    user_prompt = build_agent_prompt(question=question,memory=memory,context=context,tool_result=tool_result,conversation_summary=conversation_summary,message=message)
    total_prompt = f"""
    instruction = {AGENT_SYSTEM_PROMPT},
    tool_definitions = {TOOL_DEFINITIONS},
    input = {user_prompt}
    """
    return total_prompt

