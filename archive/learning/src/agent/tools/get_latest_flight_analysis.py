import psycopg
from src.database.flight_record_repository import get_latest_flight


def get_latest_flight_analysis() -> dict:
    try:
        row = get_latest_flight()
    except psycopg.Error:
        return {
            "status": "error",
            "analysis": None,
            "error": {
                "code": "DATABASE_ERROR",
                "message": "无法查询飞行记录"
            }
        }
        
    if row is None:
        return {"status": "not_found", "analysis": None}
    return {
        "status":"ok",
        "analysis":{
            "record_id":row["id"],
            "uav_code":row["uav_code"],
            "filename":row["filename"],
            "summary":{
                "row_count":row["row_count"],
                "max_speed":row["max_speed"],
                "max_temperature":row["max_temperature"],
                "minimum_battery":row["minimum_battery"]
            }
        }
    }
