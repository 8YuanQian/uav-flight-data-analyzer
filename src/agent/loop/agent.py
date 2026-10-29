from sentence_transformers import SentenceTransformer,CrossEncoder
from src.llm.llm_client import client
from src.llm.llm import agent_ask_llm
from src.llm.prompt.prompt import build_agent_prompt
from src.agent.tools.tools_registry import execute_tool
from src.agent.memory.short_term_memory import ConversationMessage
from src.agent.loop.state import UAVAgentState
from src.agent.tools.tool_definitions import TOOL_DEFINITIONS
from src.agent.loop.nodes.agent_node import agent_node
from src.agent.loop.nodes.tool_node import tool_node

import json

class UAVAgent:
    def __init__(self):
        self.tool_definitions = TOOL_DEFINITIONS
        self.state_message = {
            "state":UAVAgentState(query=""),
            "message":ConversationMessage()
        }

    def work(self,query):
        if query in ["exit","quit","退出"]:
            return None
        
        self.state_message["state"].start_new_turn(query)
        self.state_message["message"].add_message({
            "role":"user",
            "content":query
        })
        step = 0
        while self.state_message["state"].finished == False:
            if step >= 10:
                raise RuntimeError("Agent 超过最大执行次数")
            
            self.state_message = agent_node(state=self.state_message["state"],message=self.state_message["message"])
            if self.state_message["state"].finished == True:
                break

            self.state_message = tool_node(state=self.state_message["state"],message=self.state_message["message"])
            step += 1
        final_answer = self.state_message["state"].answer
        print("Final Answer:")
        print(self.state_message["state"].answer)

        return final_answer




    