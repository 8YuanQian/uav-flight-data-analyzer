from src.llm_client import client
from src.instructions import SYSTEM_PROMPT,AGENT_SYSTEM_PROMPT

import json


def ask_llm(prompt:str)->str:

    response = client.responses.create(
        model="deepseek-flash",
        instructions=SYSTEM_PROMPT,
        input=prompt
    )

    return response.output_text

def agent_ask_llm(prompt:str,tools_difinitions,instructions=AGENT_SYSTEM_PROMPT)->str:
    response = client.responses.create(
        model="deepseek-flash",
        instructions=instructions,
        input=prompt,
        tools=tools_difinitions,
        tool_choice="auto",
        reasoning={"effort":"none"}
    )
    return response
