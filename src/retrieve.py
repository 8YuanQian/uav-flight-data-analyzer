from src.embedding import create_embedding
from src.database import get_connection


def retrieve(query, embedding_model, metadata=None, top_k=10, threshold=0.5):
    """返回符合距离阈值的资料列表；没有结果时返回空列表。"""
    query_embedding = create_embedding(query, embedding_model)
    with get_connection() as conn:
        with conn.cursor() as cursor:
            if metadata is None:
                cursor.execute(
                    """SELECT content, source, metadata,
                              embedding <=> %s::vector AS distance
                       FROM documents
                       ORDER BY distance ASC LIMIT %s;""",
                    (query_embedding.tolist(), top_k),
                )
            else:
                cursor.execute(
                    """SELECT content, source, metadata,
                              embedding <=> %s::vector AS distance
                       FROM documents
                       WHERE metadata ->>'type' = %s
                       ORDER BY distance ASC LIMIT %s;""",
                    (query_embedding.tolist(), metadata, top_k),
                )

            rows = cursor.fetchall()

    documents = []
    for content, source, document_metadata, distance in rows:
        if distance < threshold:
            documents.append({
                "content": content,
                "source": source,
                "metadata": document_metadata,
                "distance": distance,
            })
    return documents
