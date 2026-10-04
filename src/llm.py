from src.llm_client import client
from src.instructions import SYSTEM_PROMPT


def ask_llm(prompt:str)->str:

    response = client.responses.create(
        model="deepseek-flash",

        instructions=SYSTEM_PROMPT,

        input=prompt
    )

    return response.output_text
