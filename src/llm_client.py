import os
from openai import OpenAI


api_key = os.getenv("DEEPSEEK_API_KEY")


if api_key is None:
    raise RuntimeError(
        "DEEPSEEK_API_KEY is not set"
    )


client = OpenAI(
    api_key=api_key,
    base_url="https://api.deepseek.com"
)