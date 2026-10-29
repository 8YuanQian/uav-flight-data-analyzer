from src.agent.state import UAVAgentState
from src.prompt import build_agent_prompt
from src.llm import agent_ask_llm
from src.agent.tool_definitions import TOOL_DEFINITIONS
from src.agent.memory import ConversationMessage




def agent_node(state:UAVAgentState,message:ConversationMessage):
        prompt = build_agent_prompt(question=state.query,context=state.context,tool_result=state.tool_results,message=message.get_message())
        response = agent_ask_llm(prompt=prompt,tool_definitions=TOOL_DEFINITIONS)
        for item in response.output:
            if item.type == "function_call":
                state.current_tool_call = {
                    "tool_name":item.name,
                    "tool_arguments":item.arguments,
                    "call_id":item.call_id
                }
                return {
                    "state":state,
                    "message":message
                }
        
        for item in response.output:
            if item.type == "message":
                state.answer = response.output_text
                state.finished = True
                message.add_message({
                    "role":"assistant",
                    "content":item.model_dump()
                })
                return {
                    "state":state,
                    "message":message
                }
            
        return {
            "state":state,
            "message":message
        }
