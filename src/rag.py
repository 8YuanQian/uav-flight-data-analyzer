from src.prompt import build_prompt
from src.retrieve import retrieve
from src.llm import ask_llm
from src.retrieve import retrieve
from src.reranker import rerank_documents
from src.context import build_context
from src.prompt import build_prompt
from src.llm import ask_llm


class UAVAasistent:
    def __init__(self):
        pass

    def ask(self,query):
        information = retrieve(query)
        information = rerank_documents(query, information)
        if information is None or len(information) == 0:
            return "没有找到相关信息"
        context = build_context(information)
        prompt = build_prompt(context=context,question=query)
        return ask_llm(prompt=prompt)