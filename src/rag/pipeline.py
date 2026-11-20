# 工具与评估调用同一流程，避免阈值、返回数量在两处逐渐分叉。
from dataclasses import dataclass
from time import perf_counter

from src.rag.config import DEFAULT_RETRIEVAL_CONFIG, RetrievalConfig
from src.rag.reranker import rerank_documents
from src.rag.retrieve import retrieve


@dataclass
class RetrievalRun:
    candidates: list[dict]
    vector_documents: list[dict]
    reranked_documents: list[dict]
    documents: list[dict]
    timings: dict


def run_retrieval(
    query: str, embedding_model, rerank_model=None, *,
    config: RetrievalConfig = DEFAULT_RETRIEVAL_CONFIG,
    metadata=None, connection_factory=None,
) -> RetrievalRun:
    timings = {}
    started = perf_counter()
    candidates = retrieve(
        query, embedding_model, metadata,
        top_k=config.candidate_k, threshold=config.max_cosine_distance,
        encoding=config.encoding,
        timings=timings, connection_factory=connection_factory,
    )
    retrieved = perf_counter()
    vector_documents = candidates[:config.final_k]
    selected = perf_counter()
    reranked = []
    if rerank_model is not None:
        # 只预测一次，排序对照和实际阈值对照共用同一组分数。
        reranked = rerank_documents(
            query, candidates, rerank_model,
            top_k=len(candidates), score_threshold=None,
        )
    ranked = perf_counter()
    ranking_top = reranked[:config.final_k]
    documents = (
        [doc for doc in ranking_top if doc["score"] > config.min_rerank_score]
        if rerank_model is not None else vector_documents
    )
    finished = perf_counter()
    timings.update(
        retrieval_ms=(retrieved - started) * 1000,
        rerank_ms=(ranked - selected) * 1000,
        vector_total_ms=(selected - started) * 1000,
        rerank_total_ms=((retrieved - started) + (finished - selected)) * 1000,
    )
    return RetrievalRun(candidates, vector_documents, ranking_top, documents, timings)
