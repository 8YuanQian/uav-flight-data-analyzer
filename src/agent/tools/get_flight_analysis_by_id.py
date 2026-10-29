import psycopg
from src.database.flight_record_repository import get_flight_by_id


def get_flight_analysis_by_id(id:int):
    if type(id) is not int or id <= 0:
        raise ValueError("id 必须是正整数")
    
    try:
        data = get_flight_by_id(id)
    except psycopg.Error:
        return{
            "status":"error",
            "analysis":None,
            "error": {
                "code": "DATABASE_ERROR",
                "message": "无法查询飞行记录"
            }
        }
    
    if data is None:
        return{
            "status":"not_found",
            "analysis":None
        }
    return {
        "status":"ok",
        "analysis":{
            "record_id":data["id"],
            "uav_code":data["uav_code"],
            "filename":data["filename"],
            "summary":{
                "row_count":data["row_count"],
                "max_speed":data["max_speed"],
                "max_temperature":data["max_temperature"],
                "minimum_battery":data["minimum_battery"]
            }
        }
    }
