from src.rag.config import DEFAULT_RETRIEVAL_CONFIG


def rerank_documents(
    query, documents, rerank_model,
    top_k=DEFAULT_RETRIEVAL_CONFIG.final_k,
    *, score_threshold=DEFAULT_RETRIEVAL_CONFIG.min_rerank_score,
):
    if not documents:
        return []

    # 使用查询与资料对评分，不将重排分数解释为正确概率。
    reranker_input = [(query, doc['content']) for doc in documents]

    # 每个候选资料必须对应一个分数，避免静默丢失结果。
    scores = rerank_model.predict(reranker_input)
    if len(scores) != len(documents):
        raise ValueError("重排分数数量与候选资料数量不一致")

    # 保留输入资料字段，分数转成可直接保存的 Python 浮点数。
    scored_documents = [{'document': doc, 'score': score} for doc, score in zip(documents, scores)]

    # 分数越高，资料排位越靠前。
    scored_documents.sort(key=lambda x: x['score'], reverse=True)

    # 评估排序效果时传入 None，不用分数过滤混淆排序本身的效果。
    return [
        {**doc["document"], "score": float(doc["score"])}
        for doc in scored_documents[:top_k]
        if score_threshold is None or doc["score"] > score_threshold
    ]
