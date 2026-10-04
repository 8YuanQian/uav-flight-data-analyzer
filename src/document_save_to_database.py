import json
from src.embedding import create_embedding
from psycopg.types.json import Jsonb
from src.document_store import save_document
from src.chunk import chunk_content

    
def save_document_to_database(document:dict):
    for i in document:
        contents = chunk_content(i['content'],chunk_size=500,overlap=50)
        for j in range(len(contents)):
            content = contents[j]
            source = i['source']
            metadata = Jsonb(i['metadata'])
            embedding = create_embedding(content).tolist()
            save_document(content,source,metadata,embedding)
