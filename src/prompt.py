def build_prompt(context,question):
    prompt = f"""
    资料:{context}

    问题:{question}

    请根据资料回答
    """
    return prompt