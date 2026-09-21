from fastapi.testclient import TestClient
from pathlib import Path
from api import app


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR/"data"/"data.csv"
client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_valid_csv():
    with open(DATA_PATH,"rb") as file:
        files = {"file":("data.csv",file,"text/csv")}
        response = client.post("/flights/analyze",files=files)
        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "data.csv"
        assert data["content_type"] == "text/csv"
        assert data["summary"] != False
        assert data["summary"]["row_count"] == 1000

