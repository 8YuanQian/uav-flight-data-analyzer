from src.prompt import build_prompt
from src.retrieve import retrieve
from src.llm import ask_llm
from src.reranker import rerank_documents
from src.context import build_context
from sentence_transformers import SentenceTransformer,CrossEncoder
import json
from fastapi import HTTPException


class UAVAssistant:
    def __init__(self, rerank_model, embedding_model):
        self.rerank_model = rerank_model
        self.embedding_model = embedding_model


    def ask(self,query):
        documents = retrieve(query, self.embedding_model)
        print(f"embedding id:{id(self.embedding_model)}")
        documents = rerank_documents(query, documents, self.rerank_model)
        print(f"rerank id:{id(self.rerank_model)}")
        if not documents:
            raise HTTPException(status_code=404,detail="Not relevant information found")
        context = build_context(documents)
        prompt = build_prompt(context=context,question=query)
        return json.loads(ask_llm(prompt=prompt))
