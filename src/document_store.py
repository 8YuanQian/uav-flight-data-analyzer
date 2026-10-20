from src.database import get_connection 
from src.embedding import create_embedding
from psycopg.types.json import Jsonb

def save_document(content,source=None,metadata=None,embedding=None,table_name="documents"):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT current_database();")
            print(cursor.fetchone())
            cursor.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public';"
            )
            print(cursor.fetchall())
            cursor.execute(f"""INSERT INTO {table_name}(
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

