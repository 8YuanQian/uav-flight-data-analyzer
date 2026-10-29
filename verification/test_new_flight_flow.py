"""Isolated checks for the new empty-table workflow; no database or model calls."""

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import ai_router, flight_data_router, tasks
from app.csv_upload import CsvCacheError, CsvReportError, CsvValidationError, stage_csv_upload, staged_csv_path
from src.database import flight_record_repository, uav_repository
from src.flight_data.prepare_flights import prepare_flights
from src.schemas import FlightReport


def sample_rows():
    base = {
        "uav_code": "UAV-1", "uav_model": "M1", "manufacturer": "Maker",
        "height": 10, "speed": 2, "battery": 90, "temperature": 20,
    }
    return [
        {**base, "flight_id": "group-a", "start_time": "2026-10-28 10:00", "end_time": "2026-10-28 10:05"},
        {**base, "flight_id": "group-a", "start_time": "2026-10-28 10:10", "end_time": "2026-10-28 10:20", "height": None, "battery": 80},
        {**base, "flight_id": "group-b", "start_time": "2026-10-28 11:00", "end_time": "2026-10-28 11:03", "height": 30},
    ]


def test_grouping_and_span_minutes_without_cross_group_fill():
    groups = prepare_flights(pd.DataFrame(sample_rows()))
    assert len(groups) == 2
    assert [group["csv_flight_id"] for group in groups] == ["group-a", "group-b"]
    assert groups[0]["duration_minutes"] == 20
    assert groups[0]["average_height"] == 10
    assert groups[1]["average_height"] == 30
    assert groups[0]["battery_start"] == 90
    assert groups[0]["battery_end"] == 80


@pytest.mark.parametrize("replacement", ["2026/10/28 10:00", "2026-02-30 10:00"])
def test_invalid_time_rejected(replacement):
    rows = sample_rows()
    rows[0]["start_time"] = replacement
    with pytest.raises(ValueError, match="start_time"):
        prepare_flights(pd.DataFrame(rows))


def test_overlap_rejected():
    rows = sample_rows()
    rows[1]["start_time"] = "2026-10-28 10:04"
    with pytest.raises(ValueError, match="重叠"):
        prepare_flights(pd.DataFrame(rows))


def test_save_uses_generated_id_and_does_not_insert_csv_group_id(monkeypatch):
    groups = prepare_flights(pd.DataFrame(sample_rows()))
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [(101,), (102,)]
    monkeypatch.setattr(flight_record_repository, "get_connection", lambda: connection)
    monkeypatch.setattr(flight_record_repository, "get_or_create_uav", lambda *args: 7)

    saved = flight_record_repository.save_flight_groups("sample.csv", groups)

    assert [row["id"] for row in saved] == [101, 102]
    assert all(row["uav_id"] == 7 for row in saved)
    assert cursor.execute.call_count == 2
    for call in cursor.execute.call_args_list:
        sql, values = call.args
        assert "csv_flight_id" not in sql
        assert "flight_id" not in sql
        assert "group-a" not in values and "group-b" not in values


def test_explicit_uav_registration_rejects_duplicate(monkeypatch):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (1,)
    monkeypatch.setattr(uav_repository, "get_connection", lambda: connection)
    with pytest.raises(uav_repository.UavCodeConflict, match="重复"):
        uav_repository.register_uav("UAV-1", "M1", "Maker")
    assert cursor.execute.call_count == 1


def test_import_reuses_existing_uav_without_updating_its_details():
    cursor = MagicMock()
    cursor.fetchone.side_effect = [None, (7,)]
    assert uav_repository.get_or_create_uav(cursor, "UAV-1", "M1", "Maker") == 7
    assert "ON CONFLICT (uav_code) DO NOTHING" in cursor.execute.call_args_list[0].args[0]
    assert cursor.execute.call_args_list[1].args[1] == ("UAV-1",)


def test_filtered_flight_query_uses_uav_code_parameter(monkeypatch):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    monkeypatch.setattr(flight_record_repository, "get_connection", lambda: connection)
    assert flight_record_repository.get_recent_flights(5, "UAV-1") == []
    sql, values = cursor.execute.call_args.args
    assert "uav.uav_code = %s" in sql
    assert values == ("UAV-1", 5)


def test_update_compares_version_and_returns_joined_new_record(monkeypatch):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [{"id": 9}, {"id": 9, "uav_code": "UAV-1", "version": 2}]
    monkeypatch.setattr(flight_record_repository, "get_connection", lambda: connection)
    group = prepare_flights(pd.DataFrame(sample_rows()))[0]
    result = flight_record_repository.update_flight_record(9, 1, "changed.csv", group)
    assert result["version"] == 2
    sql, values = cursor.execute.call_args_list[0].args
    assert "WHERE id = %s AND version = %s" in sql
    assert "version = version + 1" in sql
    assert values[-2:] == (9, 1)


def test_worker_report_reads_new_record_by_generated_id(monkeypatch):
    record = {field: 1 for field in tasks.REPORT_FIELDS}
    requested = []
    monkeypatch.setattr(
        tasks, "get_flight_by_id", lambda record_id: requested.append(record_id) or record
    )
    monkeypatch.setattr(
        tasks, "generate_flight_report",
        lambda summary, raise_on_error: FlightReport(
            report="测试报告", observations=[], limitations=[]
        ),
    )
    assert tasks.generate_flight_report_task.run(9)["report"] == "测试报告"
    assert requested == [9]


def test_upload_only_stages_and_queues_file(monkeypatch, tmp_path):
    monkeypatch.setenv("CSV_UPLOAD_DIR", str(tmp_path))
    app = FastAPI()
    app.include_router(ai_router.ai_flight_router)
    calls = []

    class FakeCelery:
        def send_task(self, name, args, retry):
            calls.append((name, args, retry))
            return SimpleNamespace(id="csv-task-1")

    app.state.celery_app = FakeCelery()
    csv_data = pd.DataFrame(sample_rows()).to_csv(index=False).encode("utf-8")
    response = TestClient(app).post(
        "/ai_flight/flights/report",
        files={"file": ("sample.csv", BytesIO(csv_data), "text/csv")},
    )
    assert response.status_code == 202
    assert response.json() == {"task_id": "csv-task-1", "status": "PENDING"}
    name, args, retry = calls[0]
    assert name == "uav.process_flights_csv"
    assert args[1:] == ["sample.csv", "text/csv"]
    assert retry is False
    assert staged_csv_path(args[0]).read_bytes() == csv_data


def test_worker_processes_groups_and_removes_staged_file(monkeypatch, tmp_path):
    monkeypatch.setenv("CSV_UPLOAD_DIR", str(tmp_path))
    csv_data = pd.DataFrame(sample_rows()).to_csv(index=False).encode("utf-8")
    upload_id = stage_csv_upload(BytesIO(csv_data))
    cache = SimpleNamespace(close=MagicMock())
    monkeypatch.setattr(tasks, "Redis", SimpleNamespace(from_url=lambda *a, **kw: cache))
    monkeypatch.setattr(tasks, "invalidate_flight_record_lists", lambda *a: None)
    monkeypatch.setattr(
        tasks, "save_flight_groups",
        lambda filename, groups: [
            {"id": 101 + index, "uav_id": 7, "uav_code": group["uav_code"],
             "csv_flight_id": group["csv_flight_id"]}
            for index, group in enumerate(groups)
        ],
    )
    report_calls = []

    def report(summary, *, raise_on_error):
        report_calls.append((summary, raise_on_error))
        return FlightReport(report="测试报告", observations=[], limitations=[])

    monkeypatch.setattr(tasks, "generate_flight_report", report)
    result = tasks.process_flights_csv_task.run(upload_id, "sample.csv", "text/csv")
    assert result["flight_count"] == 2
    assert [flight["id"] for flight in result["flights"]] == [101, 102]
    assert all(strict for _, strict in report_calls)
    assert len(report_calls) == 2
    assert not staged_csv_path(upload_id).exists()
    cache.close.assert_called_once()


def test_worker_rejects_invalid_csv_and_removes_staged_file(monkeypatch, tmp_path):
    monkeypatch.setenv("CSV_UPLOAD_DIR", str(tmp_path))
    upload_id = stage_csv_upload(BytesIO(b"wrong_column\n1\n"))
    with pytest.raises(CsvValidationError, match="Missing required columns"):
        tasks.process_flights_csv_task.run(upload_id, "bad.csv", "text/csv")
    assert not staged_csv_path(upload_id).exists()


def test_worker_reports_committed_ids_on_cache_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("CSV_UPLOAD_DIR", str(tmp_path))
    upload_id = stage_csv_upload(BytesIO(pd.DataFrame(sample_rows()).to_csv(index=False).encode()))
    monkeypatch.setattr(tasks, "save_flight_groups", lambda filename, groups: [
        {"id": 101, "uav_code": "UAV-1"}, {"id": 102, "uav_code": "UAV-1"}
    ])
    monkeypatch.setattr(tasks, "Redis", SimpleNamespace(from_url=lambda *a, **kw: SimpleNamespace(close=lambda: None)))

    def fail_cache(*args):
        raise tasks.CacheWriteError("cache unavailable")

    monkeypatch.setattr(tasks, "invalidate_flight_record_lists", fail_cache)
    with pytest.raises(CsvCacheError) as error:
        tasks.process_flights_csv_task.run(upload_id, "sample.csv", "text/csv")
    assert error.value.record_ids == [101, 102]
    assert not staged_csv_path(upload_id).exists()


def test_worker_reports_committed_ids_on_model_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("CSV_UPLOAD_DIR", str(tmp_path))
    upload_id = stage_csv_upload(BytesIO(pd.DataFrame(sample_rows()).to_csv(index=False).encode()))
    monkeypatch.setattr(tasks, "save_flight_groups", lambda filename, groups: [
        {"id": 101, "uav_code": "UAV-1"}, {"id": 102, "uav_code": "UAV-1"}
    ])
    monkeypatch.setattr(tasks, "Redis", SimpleNamespace(from_url=lambda *a, **kw: SimpleNamespace(close=lambda: None)))
    monkeypatch.setattr(tasks, "invalidate_flight_record_lists", lambda *a: None)

    def fail_report(*args, **kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(tasks, "generate_flight_report", fail_report)
    with pytest.raises(CsvReportError) as error:
        tasks.process_flights_csv_task.run(upload_id, "sample.csv", "text/csv")
    assert error.value.record_ids == [101, 102]
    assert not staged_csv_path(upload_id).exists()


def test_job_status_shows_csv_validation_and_cache_errors():
    app = FastAPI()
    app.include_router(ai_router.ai_flight_router)

    class FakeCelery:
        def AsyncResult(self, task_id):
            errors = {
                "invalid": CsvValidationError("缺少列"),
                "cache": CsvCacheError([101, 102]),
                "report": CsvReportError([101, 102]),
            }
            error = errors[task_id]
            return SimpleNamespace(status="FAILURE", result=error,
                                   successful=lambda: False, failed=lambda: True)

    app.state.celery_app = FakeCelery()
    client = TestClient(app)
    invalid = client.get("/ai_flight/report/jobs/invalid")
    cache = client.get("/ai_flight/report/jobs/cache")
    report = client.get("/ai_flight/report/jobs/report")
    assert invalid.json()["error"] == "INVALID_CSV"
    assert invalid.json()["detail"] == "缺少列"
    assert cache.json()["error"] == "CACHE_UPDATE_FAILED"
    assert cache.json()["detail"]["record_ids"] == [101, 102]
    assert report.json()["error"] == "REPORT_FAILED"
    assert report.json()["detail"]["record_ids"] == [101, 102]


def test_registration_duplicate_returns_409(monkeypatch):
    app = FastAPI()
    app.include_router(flight_data_router.flight_router)
    app.state.db_pool = object()

    def duplicate(**kwargs):
        raise uav_repository.UavCodeConflict("飞行器 ID 重复")

    monkeypatch.setattr(flight_data_router, "register_uav", duplicate)
    response = TestClient(app).post(
        "/flight/uavs",
        json={"uav_code": "UAV-1", "uav_model": "M1", "manufacturer": "Maker"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "飞行器 ID 重复"
