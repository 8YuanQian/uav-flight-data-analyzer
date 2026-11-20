from time import perf_counter

from src.rag.config import DEFAULT_RETRIEVAL_CONFIG
from src.rag.embedding import LEGACY_ENCODING, EmbeddingEncoding, create_query_embedding
from src.database import get_connection


def retrieve(
    query, embedding_model, metadata=None,
    top_k=DEFAULT_RETRIEVAL_CONFIG.candidate_k,
    threshold=DEFAULT_RETRIEVAL_CONFIG.max_cosine_distance,
    *, encoding: EmbeddingEncoding = LEGACY_ENCODING, timings=None, connection_factory=None,
):
    # 保留原来的位置参数；可选连接工厂仅用于隔离评估和基础测试。
    started = perf_counter()
    query_embedding = create_query_embedding(query, embedding_model, encoding=encoding)
    embedded = perf_counter()
    connect = connection_factory or get_connection
    with connect() as conn:
        with conn.cursor() as cursor:
            if metadata is None:
                cursor.execute(
                    """SELECT content, source, metadata,
                              embedding <=> %s::vector AS distance
                       FROM documents
                       ORDER BY distance ASC, id ASC LIMIT %s;""",
                    (query_embedding.tolist(), top_k),
                )
            else:
                cursor.execute(
                    """SELECT content, source, metadata,
                              embedding <=> %s::vector AS distance
                       FROM documents
                       WHERE metadata ->>'type' = %s
                       ORDER BY distance ASC, id ASC LIMIT %s;""",
                    (query_embedding.tolist(), metadata, top_k),
                )

            rows = cursor.fetchall()

    queried = perf_counter()
    documents = []
    for content, source, document_metadata, distance in rows:
        # <=> 是余弦距离，数值越小越相关；保持原先严格小于的边界。
        if distance is not None and distance < threshold:
            documents.append({
                "content": content,
                "source": source,
                "metadata": document_metadata,
                "distance": float(distance),
            })
    if timings is not None:
        timings.update(
            embedding_ms=(embedded - started) * 1000,
            database_ms=(queried - embedded) * 1000,
            distance_filter_ms=(perf_counter() - queried) * 1000,
            raw_candidate_count=len(rows),
        )
    return documents
