from src.llm.llm_client import client
from src.llm.prompt.instructions import SUMMARY_SYSTEM_PROMPT
from src.common.json_conversion import serialize_tool_result
import logging

logger = logging.getLogger(__name__)

def summarize_conversation(previous_summary:str,message_to_summarize:list[dict])->dict[str, bool | str]:
    if not message_to_summarize:
        return {
            "state":False,
            "new_summary":previous_summary
        }
    try:
        unsummarize_message = serialize_tool_result(message_to_summarize)
    except TypeError:
        logger.error("无法JSON序列化")
        return {
            "state":False,
            "new_summary":previous_summary
        }
    
    prompt = f"""
        已有历史摘要：
        {previous_summary}

        本次需要新增摘要的对话：
        {unsummarize_message}
    """
    try:
        response = client.responses.create(
            model="deepseek-flash",
            instructions=SUMMARY_SYSTEM_PROMPT,
            input=prompt
        )
    except Exception:
        logger.exception("访问摘要模型错误")
        return {
            "state":False,
            "new_summary":previous_summary
        }

    if not (response.output_text or "").strip():
        return {
            "state":False,
            "new_summary":previous_summary
        }
    return {
        "state":True,
        "new_summary":response.output_text.strip()
    }
