from src.agent.graph_state import UAVGraphState
from src.agent.context_manager import select_messages_for_summary
from src.agent.conversation_summarizer import summarize_conversation


def summary_node(state:UAVGraphState):
    select_result = select_messages_for_summary(message=state["message"],summary_cursor=state["summary_cursor"],keep_previous_turns=3)
    message_to_summarize = select_result["message_to_summarize"]
    new_cursor = select_result["new_cursor"]
    summarize_result = summarize_conversation(previous_summary=state["conversation_summary"],message_to_summarize=message_to_summarize)
    if summarize_result["state"] == True:
        return {
            "conversation_summary":summarize_result["new_summary"],
            "summary_cursor":new_cursor
        }
    else:
        return {}
