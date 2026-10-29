from src.rag.retrieve import retrieve
from src.rag.reranker import rerank_documents
from src.rag.model_factory import create_retrieval_models


def rag_search(query:str, *, embedding_model=None, rerank_model=None)->list[dict]:
    if (embedding_model is None) != (rerank_model is None):
        raise ValueError("embedding_model 和 rerank_model 必须同时提供")
    if embedding_model is None:
        model = create_retrieval_models()
        embedding_model = model["embedding_model"]
        rerank_model = model["rerank_model"]
    retrieve_data = retrieve(query=query,embedding_model=embedding_model)
    rerank_data = rerank_documents(query=query,documents=retrieve_data,rerank_model=rerank_model)
    return rerank_data
