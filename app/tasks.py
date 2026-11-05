import os

import pandas as pd
from redis import Redis

from src.cache.flight_record_cache import CacheWriteError, invalidate_flight_record_lists
from src.database.flight_record_repository import get_flight_by_id
from src.database.flight_record_repository import save_flight_groups
from src.database.flight_record_repository import user_owns_flight_records
from src.database.uav_repository import validate_import_uavs, UavOwnershipConflict
from src.auth.data_scope import require_data_user_id
from src.database.connection import close_worker_pool, open_worker_pool
from src.database.task_lease_repository import LeaseLost
from src.flight_data.load_data import load_csv_data
from src.flight_data.prepare_flights import REPORT_FIELDS, prepare_flights
from src.llm.llm_report import build_flight_report_input, generate_flight_report
from celery.signals import worker_process_init, worker_process_shutdown

from .app import celery_app
from .csv_upload import CsvCacheError, CsvReportError, CsvValidationError, staged_csv_path
from .task_lease import run_leased_task


@worker_process_init.connect
def start_database_pool_in_worker(**kwargs):
    # Celery 的 prefork 子进程不能复用父进程或 FastAPI 进程的数据库连接。
    open_worker_pool()


@worker_process_shutdown.connect
def stop_database_pool_in_worker(**kwargs):
    close_worker_pool()


@celery_app.task(name="uav.generate_flight_report", bind=True)
def generate_flight_report_task(self, record_id: int) -> dict:
    return run_leased_task(self, lambda lease, previous: _generate_report(record_id, lease))


def _generate_report(record_id, lease):
    require_data_user_id()
    if lease is not None:
        lease.assert_owned()
    record = get_flight_by_id(record_id)
    if record is None:
        raise ValueError(f"Flight record {record_id} does not exist")

    report_input = build_flight_report_input(record)
    if lease is not None:
        lease.assert_owned()
    report = generate_flight_report(report_input, raise_on_error=True)
    if lease is not None:
        lease.assert_owned()
    return report.model_dump()

# bind=True 可以将当前Celery Task实例绑定到当前任务函数，它可以让任务访问自身的状态、任务 ID、重试方法等信息
@celery_app.task(name="uav.process_flights_csv", bind=True)
def process_flights_csv_task(self, upload_id: str, filename: str | None, content_type: str | None) -> dict:
    """在 worker 中处理文件，终态确认后再删除暂存文件。"""
    path = staged_csv_path(upload_id)
    return run_leased_task(
        self,
        lambda lease, previous_result: _process_flights_csv(path, filename, content_type, lease, previous_result),
        cleanup=lambda: path.unlink(missing_ok=True),
    )


def _process_flights_csv(path, filename, content_type, lease, previous_result):
    require_data_user_id()
    # 入库结果已与任务状态一同提交时，只需继续清理缓存，不重复调用模型或入库。
    if previous_result is None:
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

        # 模型调用前排除属于其他用户或尚无归属的飞行器编号。
        if lease is not None:
            lease.assert_owned()
        try:
            validate_import_uavs(group["uav_code"] for group in groups)
        except UavOwnershipConflict as exc:
            raise CsvValidationError(str(exc)) from exc

        prepared_reports = []
        for group in groups:
            report_summary = {field: group[field] for field in REPORT_FIELDS}
            report_input = build_flight_report_input(group)
            try:
                if lease is not None:
                    lease.assert_owned()
                ai_report = generate_flight_report(report_input, raise_on_error=True)
                if lease is not None:
                    lease.assert_owned()
                prepared_reports.append({
                    "summary": report_summary,
                    "ai_report": ai_report.model_dump(),
                })
            except LeaseLost:
                raise
            except Exception as exc:
                # 任意一组失败即终止本次上传，数据库此时还没有写入。
                raise CsvReportError(group["uav_code"], group["csv_flight_id"]) from exc

        # 所有报告通过校验后，才在单个事务中保存整份 CSV 的飞行记录。
        def build_result(saved):
            flights = [{**record, **prepared} for record, prepared in zip(saved, prepared_reports)]
            return {"filename": filename, "content_type": content_type,
                    "flight_count": len(flights), "flights": flights}

        if lease is None:
            saved = save_flight_groups(filename or "uploaded.csv", groups)
            result = build_result(saved)
        else:
            # 行记录与任务结果在同一数据库事务提交；消息重投时不会重复入库。
            committed = {}

            def on_saved(cursor, saved):
                result = build_result(saved)
                lease.mark_committed(cursor, result)
                committed["result"] = result

            save_flight_groups(filename or "uploaded.csv", groups,
                               task_id=lease.task_id, task_guard=lease.check_for_write,
                               on_saved=on_saved)
            result = committed["result"]
    else:
        result = previous_result
        if lease is not None:
            lease.assert_owned()
        if not user_owns_flight_records([record["id"] for record in result["flights"]]):
            raise CsvValidationError("任务包含不属于当前账号的飞行记录")

    # 入库已提交后再清理缓存；清理失败仍报告已保存的记录编号。
    if lease is not None:
        lease.assert_owned()
    cache = Redis.from_url(
        os.getenv("REDIS_CACHE_URL", "redis://redis:6379/2"),
        decode_responses=True,
        socket_connect_timeout=0.3,
        socket_timeout=0.3,
    )
    try:
        if lease is not None:
            lease.assert_owned()
        invalidate_flight_record_lists(cache, (record["uav_code"] for record in result["flights"]),
                                      uav_ids=(record["uav_id"] for record in result["flights"]))
    except CacheWriteError as exc:
        raise CsvCacheError([record["id"] for record in result["flights"]]) from exc
    finally:
        cache.close()
    return result
