from src.agent.graph_state import UAVGraphState
from src.agent.context_manager import select_messages_for_summary,select_context_with_budget
from src.agent.conversation_summarizer import summarize_conversation


def graph_summary_node(state:UAVGraphState):
    selection = select_context_with_budget(query=state['query'],context=state['context'],message=state['message'])
    select_result = select_messages_for_summary(message=state["message"],summary_cursor=state["summary_cursor"],keep_previous_turns=selection["select_turns"])
    message_to_summarize = select_result["messages_to_summarize"]
    new_cursor = select_result["new_cursor"]
    if not message_to_summarize:
        return {}
    
    summarize_result = summarize_conversation(previous_summary=state["conversation_summary"],message_to_summarize=message_to_summarize)
    if summarize_result["state"] == True:
        return {
            "conversation_summary":summarize_result["new_summary"],
            "summary_cursor":new_cursor
        }
    else:
        return {}
