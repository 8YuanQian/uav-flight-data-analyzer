from src.embedding import create_embedding
from psycopg.types.json import Jsonb
from src.document_store import save_document
from src.chunk import chunk_content


def save_document_to_database(documents: list[dict]):
    """将一组资料分块，生成向量后保存到数据库。"""
    for document in documents:
        chunks = chunk_content(document["content"], chunk_size=500, overlap=50)
        for chunk in chunks:
            source = document["source"]
            metadata = Jsonb(document["metadata"])
            embedding = create_embedding(chunk).tolist()
            save_document(chunk, source, metadata, embedding)
