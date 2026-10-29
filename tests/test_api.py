from fastapi.testclient import TestClient
from sentence_transformers import SentenceTransformer, CrossEncoder
from src.rag.rag import UAVAssistant
from src.schemas import FlightReport
from pathlib import Path
from api import app
from io import BytesIO
import psycopg
import json
import os
import app.flight_data_router as flight_data_router
import time


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR/"data"/"data.csv"
PASSWORD = os.getenv("PASSWORD")
DB_NAME = os.getenv("UAV_DB_NAME")
TABLE_NAME = os.getenv("TABLE_NAME")
client = TestClient(app)

def fake_generate_report(monkeypatch):
    return FlightReport(
        report="test_report",
        observations=[],
        limitations=[]
    )


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_valid_csv(monkeypatch):
    monkeypatch.setattr(
        flight_data_router,"generate_flight_report",fake_generate_report
    )
    with open(DATA_PATH,"rb") as file:
        files = {"file":("data.csv",file,"text/csv")}
        response = client.post("/flights/analyze",files=files)
        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "data.csv"
        assert data["content_type"] == "text/csv"
        assert "summary" in data
        assert data["summary"]["row_count"] == 1000
        assert data["ai_report"]["report"] == "test_report"

        with psycopg.connect(host="localhost",dbname=DB_NAME,user="postgres",password=PASSWORD) as conn:
            with conn.cursor(row_factory=psycopg.rows.dict_row) as cursor:
                cursor.execute("SELECT filename,row_count FROM flight_analyses WHERE id = %s;",(data["id"],))
                row = cursor.fetchone()
        assert row is not None
        assert row["filename"] == data["filename"]
        assert row["row_count"] == data["summary"]["row_count"] 


def test_empty_csv_return_400():
    file = BytesIO(b"")
    response = client.post("/flights/analyze",files={"file":("empty.csv",file,"text/csv")})
    assert response.status_code == 400
    data = response.json()
    assert data["detail"] == "Empty file"


def test_missing_column_return_422(monkeypatch):
    monkeypatch.setattr(
        flight_data_router,"generate_flight_report",fake_generate_report
    )
    file = BytesIO(
        b'time,speed,height,temperature\n'
        b"1,2,3,4\n"
        b"5,6,7,8\n"
    )
    response = client.post("/flights/analyze",files={"file":("test.csv",file,"text/csv")})
    assert response.status_code == 422
    data = response.json()
    assert data["detail"] == "Missing required columns ['battery']"


def test_broken_csv_return_400():
    file = BytesIO(
        b"time,height,speed,battery,temperature,phase\n"
        b"0,101.5,14.8,99.7,38.7,cruise\n"
        b"1,94.8,13.5,99.5,37.0,cruise,EXTRA\n"
)
    response = client.post("/flights/analyze",files={"file":("test.csv",file,"text/csv")})
    assert response.status_code == 400
    data = response.json()
    assert data["detail"] == "Invalid CSV format"


def test_read_flight_analysis():
    value = ("insert_filename_first",20,10,13,15,56,88,46,15)
    with psycopg.connect(host="localhost",dbname=DB_NAME,user="postgres",password=PASSWORD) as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            cursor.execute("""INSERT INTO flight_analyses (
                        filename,
                        row_count,
                        average_height,
                        average_speed,
                        average_temperature,
                        max_height,
                        max_speed,
                        max_temperature,
                        minimum_battery)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        RETURNING id""",
                        value)
            row = cursor.fetchone()

    assert row is not None
    analysis_id = row["id"]
    response = client.get(f"/flights/{analysis_id}")
    assert response.status_code == 200
    data = response.json()
    assert data is not None
    assert data["id"] == analysis_id
            

def test_flight_analysis_not_found():
    response = client.get("/flights/99999")

    assert response.status_code == 404
    assert response.json()["detail"] == "NOT FOUND"


def test_flight_records():
    value_first = ("insert_filename_first",20,10,13,15,56,88,46,15)
    value_second = ("insert_filename_second",20,10,13,15,56,88,46,15)
    value_third = ("insert_filename_third",20,10,13,15,56,88,46,15)
    with psycopg.connect(host="localhost",dbname=DB_NAME,user="postgres",password=PASSWORD) as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            cursor.execute("""INSERT INTO flight_analyses (
                        filename,
                        row_count,
                        average_height,
                        average_speed,
                        average_temperature,
                        max_height,
                        max_speed,
                        max_temperature,
                        minimum_battery)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        RETURNING id""",
                        value_first)
            cursor.execute("""INSERT INTO flight_analyses (
                        filename,
                        row_count,
                        average_height,
                        average_speed,
                        average_temperature,
                        max_height,
                        max_speed,
                        max_temperature,
                        minimum_battery)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        RETURNING id""",
                        value_second)
            cursor.execute("""INSERT INTO flight_analyses (
                        filename,
                        row_count,
                        average_height,
                        average_speed,
                        average_temperature,
                        max_height,
                        max_speed,
                        max_temperature,
                        minimum_battery)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        RETURNING id""",
                        value_third)
    response = client.get("/flights?limit=2")
    assert response.status_code == 200
    data = response.json()
    assert data is not None
    assert len(data) == 2
    assert data[0]["filename"] in ["insert_filename_first","insert_filename_second","insert_filename_third"]
    assert data[1]["filename"] in ["insert_filename_first","insert_filename_second","insert_filename_third"]


# def test_flight_records_invalid_limit():
#     response = client.get("/flights?limit=0")
#     assert response.status_code == 422

def test_assistant_query(monkeypatch):
    response = client.post("/assistant/query",json={"question":"影响无人机自动返航的因素有哪些"})
    assert response.status_code == 200
    response = response.json()
    assert type(response) == list
    assert type(response["sources"]) == list



    
