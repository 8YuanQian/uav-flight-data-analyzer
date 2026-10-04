from sklearn.metrics.pairwise import cosine_similarity
from src.embedding import create_embedding
from src.database import get_connection
import numpy as np


def retrieve(query,metadata=None, top_k=10,threshold=0.5):
    query_embedding = create_embedding(query)
    with get_connection() as conn:
        with conn.cursor() as cursor:
            if metadata is None:
                cursor.execute("SELECT content,source,metadata,embedding <=> %s::vector AS distance FROM documents ORDER BY distance ASC LIMIT %s;", (query_embedding.tolist(), top_k))
            else:
                cursor.execute("SELECT content,source,metadata,embedding <=> %s::vector AS distance FROM documents WHERE metadata ->>'type' = %s ORDER BY distance ASC LIMIT %s;", (query_embedding.tolist(), metadata, top_k))    
            
            rows = cursor.fetchall()
            if not rows:
                return None
            return [{'content':row[0],'source':row[1],'metadata':row[2],'distance':row[3]} for row in rows if row[3] < threshold]


