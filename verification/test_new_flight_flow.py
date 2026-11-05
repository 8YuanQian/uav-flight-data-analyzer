"""Isolated checks for the new empty-table workflow; no database or model calls."""

from io import BytesIO
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import ai_router, flight_data_router, tasks
from app.csv_upload import CsvCacheError, CsvReportError, CsvValidationError, stage_csv_upload, staged_csv_path
from src.cache import flight_record_cache
from src.database import flight_record_repository, uav_repository
from src.flight_data.prepare_flights import prepare_flights
from src.llm import llm_report
from src.schemas import FlightReport


@pytest.fixture(autouse=True)
def isolated_uav_owner_check(monkeypatch):
    # 这些用例专测 CSV 和报表流程，真实归属校验另有权限测试覆盖。
    monkeypatch.setattr(tasks, "validate_import_uavs", lambda codes: None)
    monkeypatch.setattr(tasks, "user_owns_flight_records", lambda ids: True)


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


def test_mixed_case_uav_codes_share_csv_flight_group():
    rows = sample_rows()
    rows[1]["uav_code"] = "uav-1"
    groups = prepare_flights(pd.DataFrame(rows))
    assert len(groups) == 2
    assert groups[0]["uav_code"] == "UAV-1"
    assert groups[0]["row_count"] == 2


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
    monkeypatch.setattr(flight_record_repository, "get_or_create_uav", lambda *args, **kwargs: 7)

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


def test_same_task_cannot_insert_flights_again(monkeypatch):
    task_id = uuid4()
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (True,)
    monkeypatch.setattr(flight_record_repository, "get_connection", lambda: connection)
    create_uav = MagicMock()
    monkeypatch.setattr(flight_record_repository, "get_or_create_uav", create_uav)
    guard = MagicMock()
    on_saved = MagicMock()

    with pytest.raises(flight_record_repository.FlightTaskAlreadyWritten):
        flight_record_repository.save_flight_groups(
            "sample.csv", [{}], task_id=task_id, task_guard=guard, on_saved=on_saved
        )

    guard.assert_called_once_with(cursor)
    assert cursor.execute.call_count == 1
    assert cursor.execute.call_args.args[1] == (task_id, task_id)
    create_uav.assert_not_called()
    on_saved.assert_not_called()


def test_new_flight_rows_carry_task_id_and_commit_with_task_state(monkeypatch):
    task_id = uuid4()
    group = prepare_flights(pd.DataFrame(sample_rows()))[0]
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [(False,), (101,)]
    monkeypatch.setattr(flight_record_repository, "get_connection", lambda: connection)
    create_uav = MagicMock(return_value=7)
    monkeypatch.setattr(flight_record_repository, "get_or_create_uav", create_uav)
    guard = MagicMock()
    on_saved = MagicMock()

    saved = flight_record_repository.save_flight_groups(
        "sample.csv", [group], task_id=task_id, task_guard=guard, on_saved=on_saved
    )

    guard.assert_called_once_with(cursor)
    create_uav.assert_called_once_with(cursor, "UAV-1", "M1", "Maker", task_id=task_id)
    sql, params = cursor.execute.call_args.args
    assert "task_id" in sql and "csv_flight_id" not in sql
    assert params[2] == task_id
    on_saved.assert_called_once_with(cursor, saved)


def test_explicit_registration_checks_uppercase_code(monkeypatch):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (1,)
    monkeypatch.setattr(uav_repository, "get_connection", lambda: connection)
    with pytest.raises(uav_repository.UavCodeConflict, match="重复"):
        uav_repository.register_uav(" uav-1 ", "M1", "Maker")
    assert cursor.execute.call_args.args[1] == ("UAV-1",)


def test_import_reuses_existing_uav_without_updating_its_details():
    cursor = MagicMock()
    cursor.fetchone.side_effect = [None, (7,)]
    task_id = uuid4()
    assert uav_repository.get_or_create_uav(cursor, "uav-1", "M1", "Maker", task_id=task_id) == 7
    assert "ON CONFLICT (uav_code) DO NOTHING" in cursor.execute.call_args_list[0].args[0]
    assert cursor.execute.call_args_list[0].args[1][0] == "UAV-1"
    assert cursor.execute.call_args_list[0].args[1][-2:] == (task_id, 1)
    assert cursor.execute.call_args_list[1].args[1] == ("UAV-1", 1)


def test_filtered_flight_query_uses_uav_code_parameter(monkeypatch):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    monkeypatch.setattr(flight_record_repository, "get_connection", lambda: connection)
    assert flight_record_repository.get_recent_flights(5, "uav-1") == []
    sql, values = cursor.execute.call_args.args
    assert "uav.uav_code = %s" in sql
    assert "flight.task_id" not in sql and "flight.*" not in sql
    assert values == (1, 1, "UAV-1", 5)


def test_flight_list_cache_key_ignores_uav_code_case():
    assert flight_record_cache._list_key(5, "uav-1") == flight_record_cache._list_key(5, "UAV-1")


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
    assert values[-4:] == (9, 1, 1, 1)


def test_worker_report_reads_new_record_by_generated_id(monkeypatch):
    record = prepare_flights(pd.DataFrame(sample_rows()))[0]
    requested = []
    monkeypatch.setattr(
        tasks, "get_flight_by_id", lambda record_id: requested.append(record_id) or record
    )
    monkeypatch.setattr(
        tasks, "generate_flight_report",
        lambda summary, raise_on_error: FlightReport(
            conclusion="测试报告", observations=[], attention_items=[], limitations=[]
        ),
    )
    assert tasks.generate_flight_report_task.run(9)["conclusion"] == "测试报告"
    assert requested == [9]


def test_report_input_labels_one_flight_and_serializes_database_decimal(monkeypatch):
    record = prepare_flights(pd.DataFrame(sample_rows()))[0]
    record["duration_minutes"] = Decimal("20.00")
    report_input = llm_report.build_flight_report_input(record)
    assert report_input["flight"]["csv_flight_id"] == "group-a"
    assert report_input["flight"]["sample_row_count"] == 2
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(output_text=(
            '{"conclusion":"本次飞行已完成","observations":[],"attention_items":[],"limitations":[]}'
        ))

    monkeypatch.setattr(llm_report, "client", SimpleNamespace(responses=SimpleNamespace(create=create)))
    result = llm_report.generate_flight_report(report_input, raise_on_error=True)
    assert result.conclusion == "本次飞行已完成"
    assert '"sample_row_count": 2' in captured["input"]
    assert '"duration_minutes": 20.0' in captured["input"]
    assert "采样行数，不是飞行次数" in captured["instructions"]


def test_upload_only_stages_and_queues_file(monkeypatch, tmp_path):
    monkeypatch.setenv("CSV_UPLOAD_DIR", str(tmp_path))
    app = FastAPI()
    app.include_router(ai_router.ai_flight_router)
    calls = []

    class FakeCelery:
        def send_task(self, name, args, task_id, retry):
            calls.append((name, args, task_id, retry))
            return SimpleNamespace(id=task_id)

    app.state.celery_app = FakeCelery()
    # 此用例只验证暂存和投递，登录与数据库占键由专门的幂等用例覆盖。
    from app.auth_dependencies import require_user
    from app.database_dependency import database_pool_for_route
    from src.auth.security import AuthIdentity
    app.dependency_overrides[require_user] = lambda: AuthIdentity(1, "test-user")

    async def no_database_pool():
        yield

    app.dependency_overrides[database_pool_for_route] = no_database_pool
    monkeypatch.setattr(ai_router, "reserve_csv_upload", lambda *args: None)
    monkeypatch.setattr(ai_router, "register_task", lambda *args: None)
    csv_data = pd.DataFrame(sample_rows()).to_csv(index=False).encode("utf-8")
    response = TestClient(app).post(
        "/ai_flight/flights/report",
        files={"file": ("sample.csv", BytesIO(csv_data), "text/csv")},
        data={"idempotency_key": "525f22e7-57b1-47de-8f51-cc96d31598a1"},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "PENDING"
    name, args, task_id, retry = calls[0]
    assert name == "uav.process_flights_csv"
    assert args[1:] == ["sample.csv", "text/csv"]
    assert task_id == response.json()["task_id"]
    assert retry is False
    assert staged_csv_path(args[0]).read_bytes() == csv_data


def test_worker_processes_groups_and_removes_staged_file(monkeypatch, tmp_path):
    monkeypatch.setenv("CSV_UPLOAD_DIR", str(tmp_path))
    csv_data = pd.DataFrame(sample_rows()).to_csv(index=False).encode("utf-8")
    upload_id = stage_csv_upload(BytesIO(csv_data))
    cache = SimpleNamespace(close=MagicMock())
    monkeypatch.setattr(tasks, "Redis", SimpleNamespace(from_url=lambda *a, **kw: cache))
    monkeypatch.setattr(tasks, "invalidate_flight_record_lists", lambda *a, **kw: None)
    events = []

    def save(filename, groups):
        events.append("save")
        return [
            {"id": 101 + index, "uav_id": 7, "uav_code": group["uav_code"],
             "csv_flight_id": group["csv_flight_id"]}
            for index, group in enumerate(groups)
        ]

    monkeypatch.setattr(tasks, "save_flight_groups", save)
    report_calls = []

    def report(summary, *, raise_on_error):
        events.append("report")
        report_calls.append((summary, raise_on_error))
        return FlightReport(conclusion="测试报告", observations=[], attention_items=[], limitations=[])

    monkeypatch.setattr(tasks, "generate_flight_report", report)
    result = tasks.process_flights_csv_task.run(upload_id, "sample.csv", "text/csv")
    assert result["flight_count"] == 2
    assert [flight["id"] for flight in result["flights"]] == [101, 102]
    assert all(strict for _, strict in report_calls)
    assert len(report_calls) == 2
    assert events == ["report", "report", "save"]
    assert [item["flight"]["csv_flight_id"] for item, _ in report_calls] == ["group-a", "group-b"]
    assert [item["flight"]["sample_row_count"] for item, _ in report_calls] == [2, 1]
    assert result["flights"][0]["ai_report"]["conclusion"] == "测试报告"
    assert not staged_csv_path(upload_id).exists()
    cache.close.assert_called_once()


def test_committed_csv_redelivery_skips_model_and_database(monkeypatch, tmp_path):
    previous_result = {
        "filename": "sample.csv", "content_type": "text/csv", "flight_count": 1,
        "flights": [{"id": 101, "uav_code": "UAV-1", "uav_id": 7}],
    }
    saved = MagicMock()
    report = MagicMock()
    invalidated = MagicMock()
    cache = SimpleNamespace(close=MagicMock())
    monkeypatch.setattr(tasks, "save_flight_groups", saved)
    monkeypatch.setattr(tasks, "generate_flight_report", report)
    monkeypatch.setattr(tasks, "invalidate_flight_record_lists", invalidated)
    monkeypatch.setattr(tasks, "Redis", SimpleNamespace(from_url=lambda *a, **kw: cache))
    lease = SimpleNamespace(assert_owned=MagicMock())

    result = tasks._process_flights_csv(
        tmp_path / "already-committed.csv", "sample.csv", "text/csv", lease, previous_result
    )

    assert result is previous_result
    saved.assert_not_called()
    report.assert_not_called()
    invalidated.assert_called_once()
    cache.close.assert_called_once()


def test_worker_passes_task_id_to_atomic_database_write(monkeypatch):
    path = MagicMock()
    path.open.return_value.__enter__.return_value = BytesIO(
        pd.DataFrame(sample_rows()).to_csv(index=False).encode()
    )
    task_id = uuid4()
    lease = SimpleNamespace(
        task_id=task_id, assert_owned=MagicMock(),
        check_for_write=MagicMock(), mark_committed=MagicMock(),
    )
    monkeypatch.setattr(tasks, "generate_flight_report", lambda *a, **kw: FlightReport(
        conclusion="测试报告", observations=[], attention_items=[], limitations=[]
    ))
    cache = SimpleNamespace(close=MagicMock())
    monkeypatch.setattr(tasks, "Redis", SimpleNamespace(from_url=lambda *a, **kw: cache))
    monkeypatch.setattr(tasks, "invalidate_flight_record_lists", lambda *a, **kw: None)
    received = {}

    def save(filename, groups, *, task_id, task_guard, on_saved):
        received["task_id"] = task_id
        cursor = MagicMock()
        task_guard(cursor)
        saved = [
            {"id": 101 + index, "uav_code": group["uav_code"], "uav_id": 7,
             "csv_flight_id": group["csv_flight_id"]}
            for index, group in enumerate(groups)
        ]
        on_saved(cursor, saved)
        return saved

    monkeypatch.setattr(tasks, "save_flight_groups", save)
    result = tasks._process_flights_csv(path, "sample.csv", "text/csv", lease, None)

    assert received["task_id"] == task_id
    assert result["flight_count"] == 2
    lease.check_for_write.assert_called_once()
    lease.mark_committed.assert_called_once()
    assert lease.mark_committed.call_args.args[1] == result


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
        {"id": 101, "uav_code": "UAV-1", "uav_id": 7}, {"id": 102, "uav_code": "UAV-1", "uav_id": 7}
    ])
    monkeypatch.setattr(tasks, "Redis", SimpleNamespace(from_url=lambda *a, **kw: SimpleNamespace(close=lambda: None)))
    monkeypatch.setattr(
        tasks, "generate_flight_report",
        lambda *a, **kw: FlightReport(
            conclusion="测试报告", observations=[], attention_items=[], limitations=[]
        ),
    )

    def fail_cache(*args, **kwargs):
        raise tasks.CacheWriteError("cache unavailable")

    monkeypatch.setattr(tasks, "invalidate_flight_record_lists", fail_cache)
    with pytest.raises(CsvCacheError) as error:
        tasks.process_flights_csv_task.run(upload_id, "sample.csv", "text/csv")
    assert error.value.record_ids == [101, 102]
    assert not staged_csv_path(upload_id).exists()


def test_second_flight_report_failure_prevents_all_database_writes(monkeypatch, tmp_path):
    monkeypatch.setenv("CSV_UPLOAD_DIR", str(tmp_path))
    upload_id = stage_csv_upload(BytesIO(pd.DataFrame(sample_rows()).to_csv(index=False).encode()))
    saved = MagicMock()
    monkeypatch.setattr(tasks, "save_flight_groups", saved)
    model_calls = []

    def fail_report(report_input, *, raise_on_error):
        model_calls.append(report_input["flight"]["csv_flight_id"])
        if len(model_calls) == 2:
            raise RuntimeError("model unavailable")
        return FlightReport(conclusion="测试报告", observations=[], attention_items=[], limitations=[])

    monkeypatch.setattr(tasks, "generate_flight_report", fail_report)
    with pytest.raises(CsvReportError) as error:
        tasks.process_flights_csv_task.run(upload_id, "sample.csv", "text/csv")
    assert (error.value.uav_code, error.value.csv_flight_id) == ("UAV-1", "group-b")
    assert model_calls == ["group-a", "group-b"]
    saved.assert_not_called()
    assert not staged_csv_path(upload_id).exists()


def test_invalid_model_report_does_not_save_any_flights(monkeypatch, tmp_path):
    monkeypatch.setenv("CSV_UPLOAD_DIR", str(tmp_path))
    upload_id = stage_csv_upload(BytesIO(pd.DataFrame(sample_rows()).to_csv(index=False).encode()))
    saved = MagicMock()
    monkeypatch.setattr(tasks, "save_flight_groups", saved)
    monkeypatch.setattr(tasks, "generate_flight_report", llm_report.generate_flight_report)
    monkeypatch.setattr(llm_report, "client", SimpleNamespace(
        responses=SimpleNamespace(create=lambda **kwargs: SimpleNamespace(
            output_text='{"report":"旧格式","observations":[],"limitations":[]}'
        ))
    ))

    with pytest.raises(CsvReportError) as error:
        tasks.process_flights_csv_task.run(upload_id, "sample.csv", "text/csv")
    assert error.value.csv_flight_id == "group-a"
    saved.assert_not_called()


def test_database_failure_happens_after_reports_without_cache_invalidation(monkeypatch, tmp_path):
    monkeypatch.setenv("CSV_UPLOAD_DIR", str(tmp_path))
    upload_id = stage_csv_upload(BytesIO(pd.DataFrame(sample_rows()).to_csv(index=False).encode()))
    report_calls = []

    def report(report_input, *, raise_on_error):
        report_calls.append(report_input["flight"]["csv_flight_id"])
        return FlightReport(conclusion="测试报告", observations=[], attention_items=[], limitations=[])

    def fail_save(filename, groups):
        raise RuntimeError("database unavailable")

    cache = MagicMock()
    monkeypatch.setattr(tasks, "generate_flight_report", report)
    monkeypatch.setattr(tasks, "save_flight_groups", fail_save)
    monkeypatch.setattr(tasks, "Redis", SimpleNamespace(from_url=cache))
    with pytest.raises(RuntimeError, match="database unavailable"):
        tasks.process_flights_csv_task.run(upload_id, "sample.csv", "text/csv")
    assert report_calls == ["group-a", "group-b"]
    cache.assert_not_called()


def test_job_status_shows_csv_validation_and_cache_errors(monkeypatch):
    app = FastAPI()
    app.include_router(ai_router.ai_flight_router)
    ids = {name: str(uuid4()) for name in ("invalid", "cache", "report")}

    class FakeCelery:
        def AsyncResult(self, task_id):
            errors = {
                ids["invalid"]: CsvValidationError("缺少列"),
                ids["cache"]: CsvCacheError([101, 102]),
                ids["report"]: CsvReportError("UAV-1", "group-b"),
            }
            error = errors[task_id]
            return SimpleNamespace(status="FAILURE", result=error,
                                   successful=lambda: False, failed=lambda: True)

    app.state.celery_app = FakeCelery()
    from app.database_dependency import database_pool_for_route
    from app.auth_dependencies import require_user
    from src.auth.security import AuthIdentity

    async def no_database_pool():
        yield

    app.dependency_overrides[database_pool_for_route] = no_database_pool
    app.dependency_overrides[require_user] = lambda: AuthIdentity(1, "test-user")
    monkeypatch.setattr(ai_router, "get_task_owner", lambda task_id: 1)
    monkeypatch.setattr(ai_router, "get_task_state", lambda task_id: None)
    client = TestClient(app)
    invalid = client.get(f"/ai_flight/report/jobs/{ids['invalid']}")
    cache = client.get(f"/ai_flight/report/jobs/{ids['cache']}")
    report = client.get(f"/ai_flight/report/jobs/{ids['report']}")
    assert invalid.json()["error"] == "INVALID_CSV"
    assert invalid.json()["detail"] == "缺少列"
    assert cache.json()["error"] == "CACHE_UPDATE_FAILED"
    assert cache.json()["detail"]["record_ids"] == [101, 102]
    assert report.json()["error"] == "REPORT_FAILED"
    assert report.json()["detail"] == {
        "message": "AI 报告生成失败，本次上传的飞行记录未入库",
        "uav_code": "UAV-1",
        "csv_flight_id": "group-b",
    }


def test_registration_duplicate_returns_409(monkeypatch):
    from app.auth_dependencies import require_user
    from src.auth.security import AuthIdentity
    app = FastAPI()
    app.dependency_overrides[require_user] = lambda: AuthIdentity(1, "test-user")
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
