from src.rag.embedding import LEGACY_ENCODING, EmbeddingEncoding, create_passage_embeddings
from psycopg.types.json import Jsonb
from src.database.document_store import save_document
from src.rag.chunk import chunk_content


def save_document_to_database(documents: list[dict], embedding_model, table_name,
                              *, encoding: EmbeddingEncoding = LEGACY_ENCODING):
    """将一组资料分块，生成向量后保存到数据库。"""
    for document in documents:
        chunks = chunk_content(document["content"], chunk_size=500, overlap=50)
        for chunk in chunks:
            source = document["source"]
            metadata = Jsonb(document["metadata"])
            embedding = create_passage_embeddings(chunk, embedding_model, encoding=encoding).tolist()
            save_document(chunk, source, metadata, embedding, table_name)
