"""当前飞行器与飞行记录路由的业务测试。"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import flight_data_router as router
from src.schemas import FlightRecord, UavCreate


def request_with_cache():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(cache=object())))


def test_create_uav_normalizes_code(monkeypatch):
    captured = {}
    monkeypatch.setattr(router, "register_uav", lambda **values: captured.update(values) or 12)

    result = router.create_uav(UavCreate(
        uav_code=" uav-01 ", uav_model=" Test Model ", manufacturer=" Test Maker "
    ))

    assert result == {
        "id": 12, "uav_code": "UAV-01",
        "uav_model": "Test Model", "manufacturer": "Test Maker",
    }
    assert captured["uav_code"] == "UAV-01"


def test_create_uav_rejects_duplicate(monkeypatch):
    def duplicate(**values):
        raise router.UavCodeConflict()
    monkeypatch.setattr(router, "register_uav", duplicate)

    with pytest.raises(HTTPException) as error:
        router.create_uav(UavCreate(
            uav_code="UAV-01", uav_model="Model", manufacturer="Maker"
        ))
    assert error.value.status_code == 409


def test_validate_csv_interval_uses_current_fields():
    record = FlightRecord(
        uav_code="UAV-01", uav_model="Model", manufacturer="Maker",
        flight_id="CSV-01", start_time="2026-01-01 10:00",
        end_time="2026-01-01 10:30", height=20, speed=8,
        battery=90, temperature=25,
    )

    result = router.flights_validate(record)

    assert result["status"] == "valid"
    assert result["record"]["flight_id"] == "CSV-01"


def test_read_flight_record_not_found(monkeypatch):
    monkeypatch.setattr(router, "get_cached_flight_record", lambda cache, record_id: None)

    with pytest.raises(HTTPException) as error:
        router.read_flight_record(999, request_with_cache())
    assert error.value.status_code == 404


def test_read_flight_record_uses_database_record_id(monkeypatch):
    calls = []
    monkeypatch.setattr(
        router, "get_cached_flight_record",
        lambda cache, record_id: calls.append(record_id) or {"id": record_id},
    )

    assert router.read_flight_record(17, request_with_cache()) == {"id": 17}
    assert calls == [17]


def test_save_document_targets_retrieval_table(monkeypatch):
    from io import BytesIO
    from fastapi import UploadFile

    calls = []
    monkeypatch.setattr(router, "load_json_data", lambda file: [{"text": "doc"}])
    monkeypatch.setattr(
        router, "save_document_to_database",
        lambda data, model, table: calls.append((data, model, table)),
    )
    model = object()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        embedding_model=model
    )))
    router.save_document(UploadFile(filename="doc.json", file=BytesIO(b"[]")), request)
    assert calls == [([{"text": "doc"}], model, "documents")]
