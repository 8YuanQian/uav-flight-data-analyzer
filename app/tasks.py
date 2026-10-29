import os

import pandas as pd
from redis import Redis

from src.cache.flight_record_cache import CacheWriteError, invalidate_flight_record_lists
from src.database.flight_record_repository import get_flight_by_id
from src.database.flight_record_repository import save_flight_groups
from src.database.connection import close_worker_pool, open_worker_pool
from src.flight_data.load_data import load_csv_data
from src.flight_data.prepare_flights import REPORT_FIELDS, prepare_flights
from src.llm.llm_report import generate_flight_report
from celery.signals import worker_process_init, worker_process_shutdown

from .app import celery_app
from .csv_upload import CsvCacheError, CsvReportError, CsvValidationError, staged_csv_path


@worker_process_init.connect
def start_database_pool_in_worker(**kwargs):
    # Celery 的 prefork 子进程不能复用父进程或 FastAPI 进程的数据库连接。
    open_worker_pool()


@worker_process_shutdown.connect
def stop_database_pool_in_worker(**kwargs):
    close_worker_pool()


@celery_app.task(name="uav.generate_flight_report")
def generate_flight_report_task(record_id: int) -> dict:
    record = get_flight_by_id(record_id)
    if record is None:
        raise ValueError(f"Flight record {record_id} does not exist")

    summary = {field: record[field] for field in REPORT_FIELDS}
    report = generate_flight_report(summary, raise_on_error=True)
    return report.model_dump()


@celery_app.task(name="uav.process_flights_csv")
def process_flights_csv_task(upload_id: str, filename: str | None, content_type: str | None) -> dict:
    """Run the former upload pipeline in the worker and remove the staged file."""
    path = staged_csv_path(upload_id)
    try:
        try:
            with path.open("rb") as uploaded:
                file_data = load_csv_data(uploaded)
        except pd.errors.EmptyDataError as exc:
            raise CsvValidationError("Empty file") from exc
        except pd.errors.ParserError as exc:
            raise CsvValidationError("Invalid CSV format") from exc
        except UnicodeDecodeError as exc:
            raise CsvValidationError("CSV encoding is invalid") from exc

        try:
            groups = prepare_flights(file_data)
        except ValueError as exc:
            raise CsvValidationError(str(exc)) from exc

        saved = save_flight_groups(filename or "uploaded.csv", groups)

        # The import is committed before cache invalidation. Report committed IDs on failure.
        cache = Redis.from_url(
            os.getenv("REDIS_CACHE_URL", "redis://redis:6379/2"),
            decode_responses=True,
            socket_connect_timeout=0.3,
            socket_timeout=0.3,
        )
        try:
            invalidate_flight_record_lists(cache, (record["uav_code"] for record in saved))
        except CacheWriteError as exc:
            raise CsvCacheError([record["id"] for record in saved]) from exc
        finally:
            cache.close()

        flights = []
        for group, record in zip(groups, saved):
            report_summary = {field: group[field] for field in REPORT_FIELDS}
            try:
                ai_report = generate_flight_report(report_summary, raise_on_error=True)
            except Exception as exc:
                raise CsvReportError([saved_record["id"] for saved_record in saved]) from exc
            flights.append({
                **record,
                "summary": report_summary,
                "ai_report": ai_report.model_dump(),
            })
        return {
            "filename": filename,
            "content_type": content_type,
            "flight_count": len(flights),
            "flights": flights,
        }
    finally:
        path.unlink(missing_ok=True)
