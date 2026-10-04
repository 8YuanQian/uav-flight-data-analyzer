from src.database import get_connection 
from src.embedding import create_embedding
from psycopg.types.json import Jsonb

def save_document(content,source=None,metadata=None,embedding=None):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""INSERT INTO documents(
                        content,
                        source,
                        metadata,
                        embedding)
                        VALUES(%s,%s,%s,%s)
                        RETURNING id;""",
                        (content,
                        source,
                        metadata,
                        embedding)
            )

