import os 
os.environ["UAV_DB_NAME"] = "uav_project_test"
os.environ["TABLE_NAME"] = "test_documents"
import pytest
import psycopg


DB_NAME = os.getenv("UAV_DB_NAME","uav_project")
PASSWORD = os.getenv("PASSWORD")

if DB_NAME != "uav_project_test":
    raise RuntimeError(
        "Tests must use uav_project_test"
    )

@pytest.fixture(autouse=True)
def clean():
    with psycopg.connect(host="localhost",dbname=DB_NAME,user="postgres",password=PASSWORD) as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            cursor.execute("DELETE FROM flight_analyses")

    yield

    with psycopg.connect(host="localhost",dbname=DB_NAME,user="postgres",password=PASSWORD) as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            cursor.execute("DELETE FROM flight_analyses")