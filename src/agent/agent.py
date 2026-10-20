from sentence_transformers import SentenceTransformer,CrossEncoder
from src.llm_client import client
from src.llm import agent_ask_llm
from src.prompt import build_agent_prompt
from src.agent.tools_registry import execute_tool
from src.agent.memory import ConversationMessage
from src.agent.state import UAVAgentState
from src.agent.tool_difinitions import TOOLS_DEFINITIONS
from src.agent.nodes.agent_node import agent_node
from src.agent.nodes.tool_node import tool_node

import json

class UAVAgent:
    def __init__(self):
        self.TOOLS_DEFINITIONS = TOOLS_DEFINITIONS
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




    