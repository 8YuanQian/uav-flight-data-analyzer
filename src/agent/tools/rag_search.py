from src.rag.config import DEFAULT_RETRIEVAL_CONFIG
from src.rag.pipeline import run_retrieval
from src.rag.model_factory import create_retrieval_models


def rag_search(query:str, *, embedding_model=None, rerank_model=None)->list[dict]:
    if (embedding_model is None) != (rerank_model is None):
        raise ValueError("embedding_model 和 rerank_model 必须同时提供")
    if embedding_model is None:
        model = create_retrieval_models()
        embedding_model = model["embedding_model"]
        rerank_model = model["rerank_model"]
    # 工具只返回资料；评估计时和标注不会进入 LLM 上下文。
    return run_retrieval(
        query, embedding_model, rerank_model, config=DEFAULT_RETRIEVAL_CONFIG,
    ).documents
