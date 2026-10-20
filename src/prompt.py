

def build_prompt(information,question):
    prompt = f"""
    资料:{information}

    问题:{question}

    请根据资料回答
    """
    return prompt

def build_agent_prompt(question,memory=None,context=None,tool_result=None,message=None):
    prompt = f"""
    问题:{question}

    上下文:{context}

    消息历史:{message}

    工具调用结果:{tool_result}
    """
    return prompt
