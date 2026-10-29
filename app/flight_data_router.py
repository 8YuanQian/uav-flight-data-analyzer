import pandas as pd
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile,Request

from .database_dependency import database_pool_for_route
from src.cache.flight_record_cache import (
    CacheWriteError,
    get_cached_flight_record,
    get_cached_flight_records,
    invalidate_flight_record_after_update,
)
from src.database.flight_record_repository import (
    FlightRecordVersionConflict,
    update_flight_record,
)
from src.database.uav_repository import UavCodeConflict, register_uav
from src.flight_data.load_data import load_json_data
from src.rag.document_save_to_database import save_document_to_database
from src.schemas import FlightRecord, FlightRecordUpdate, UavCreate


flight_router = APIRouter(prefix="/flight")


@flight_router.post("/uavs", status_code=201, dependencies=[Depends(database_pool_for_route)])
def create_uav(data: UavCreate):
    values = {name: getattr(data, name).strip() for name in ("uav_code", "uav_model", "manufacturer")}
    if not all(values.values()):
        raise HTTPException(status_code=422, detail="飞行器编号、型号和制造商不能为空")
    try:
        uav_id = register_uav(**values)
    except UavCodeConflict:
        raise HTTPException(status_code=409, detail="飞行器 ID 重复")
    except psycopg.Error:
        raise HTTPException(status_code=500, detail="Database Error")
    return {"id": uav_id, **values}


@flight_router.post("/flights/validate")
def flights_validate(record: FlightRecord):
    record_data = record.model_dump()
    return {
        "status": "valid",
        "record": record_data,
    }


@flight_router.get("/flights/{record_id}", dependencies=[Depends(database_pool_for_route)])
def read_flight_record(record_id: int, request: Request):
    try:
        # 缓存命中直接返回；未命中或读取失败时由缓存层查询数据库。
        data = get_cached_flight_record(request.app.state.cache, record_id)
    except psycopg.Error:
        raise HTTPException(status_code=500, detail="Database Error")
    except CacheWriteError:
        raise HTTPException(status_code=503, detail="缓存写入失败，请稍后重试")

    if data is None:
        raise HTTPException(status_code=404, detail="NOT FOUND")
    else:
        return data


@flight_router.put("/flights/{record_id}", dependencies=[Depends(database_pool_for_route)])
def replace_flight_record(record_id: int, changes: FlightRecordUpdate, request: Request):
    """Replace a new-table record if the version has not changed."""
    values = changes.model_dump()
    expected_version = values.pop("version")
    filename = values.pop("filename")
    if (values["start_time"].utcoffset() is None or values["end_time"].utcoffset() is None
            or values["end_time"] <= values["start_time"]):
        raise HTTPException(status_code=422, detail="需要带时区且结束晚于开始的时间")
    values["duration_minutes"] = round(
        (values["end_time"] - values["start_time"]).total_seconds() / 60, 2
    )
    try:
        updated = update_flight_record(record_id, expected_version, filename, values)
    except FlightRecordVersionConflict:
        raise HTTPException(status_code=409, detail="记录已被更新，请重新获取最新版本")
    except psycopg.Error:
        raise HTTPException(status_code=500, detail="Database Error")

    if updated is None:
        raise HTTPException(status_code=404, detail="NOT FOUND")

    try:
        invalidate_flight_record_after_update(
            request.app.state.cache, record_id, updated["uav_code"]
        )
    except CacheWriteError:
        # 数据库事务已提交；返回新版本，方便调用方确认写入结果。
        raise HTTPException(
            status_code=503,
            detail={
                "message": "记录已更新，但缓存清除失败；读取接口可能暂时返回旧数据，请勿用旧版本重试",
                "record_id": record_id,
                "version": updated["version"],
            },
        )
    return updated


@flight_router.get("/flights", dependencies=[Depends(database_pool_for_route)])
def flight_records(
    request: Request,
    limit: int = Query(default=5, ge=1, le=100),
    uav_code: str | None = Query(default=None, min_length=1),
):
    try:
        # 缓存键包含 limit，避免不同页长共用同一份列表。
        data = get_cached_flight_records(request.app.state.cache, limit, uav_code)
    except psycopg.Error:
        raise HTTPException(status_code=500, detail="Database Error")
    except CacheWriteError:
        raise HTTPException(status_code=503, detail="缓存写入失败，请稍后重试")

    if data is None:
        return {
            "status": "NOT FOUND",
            "detail": "Not found any data",
        }
    return data


@flight_router.post("/save/document", dependencies=[Depends(database_pool_for_route)])
def save_document(file: UploadFile, request: Request):
    file_object = file.file
    try:
        file_data = load_json_data(file_object)
    except pd.errors.EmptyDataError:
        raise HTTPException(status_code=400, detail="Empty file")
    except pd.errors.ParserError:
        raise HTTPException(status_code=400, detail="Invalid json format")

    save_document_to_database(file_data, request.app.state.embedding_model, "test_documents")
