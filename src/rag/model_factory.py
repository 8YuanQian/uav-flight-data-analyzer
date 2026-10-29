from sentence_transformers import SentenceTransformer,CrossEncoder
from functools import lru_cache


@lru_cache(maxsize=1)
def create_retrieval_models():
    embedding_model = SentenceTransformer("intfloat/multilingual-e5-base")
    rerank_model = CrossEncoder("BAAI/bge-reranker-base")
    return{
        "embedding_model":embedding_model,
        "rerank_model":rerank_model
    }
