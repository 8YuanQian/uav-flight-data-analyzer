import psycopg
import os

from src.database import get_flight_records,get_flight_analysis

PASSWORD = os.getenv("PASSWORD")
DB_name = os.getenv("UAV_DB_NAME")

def get_latest_flight_analysis() -> dict:
    try:
        rows=get_flight_records(1)
    except psycopg.Error:
        return {
            "status": "error",
            "analysis": None,
            "error": {
                "code": "DATABASE_ERROR",
                "message": "无法查询飞行分析记录"
            }
        }
        
    if len(rows) == 0:
        return {"status": "not_found", "analysis": None}
    return {
        "status":"ok",
        "analysis":{
            "analysis_id":rows[0]["id"],
            "filename":rows[0]["filename"],
            "summary":{
                "row_count":rows[0]["row_count"],
                "max_speed":rows[0]["max_speed"],
                "max_temperature":rows[0]["max_temperature"],
                "minimum_battery":rows[0]["minimum_battery"]
            }
        }
    }


def get_flight_analysis_by_id(id:int):
    if type(id) is not int or id <= 0:
        raise ValueError("id 必须是正整数")
    
    try:
        data = get_flight_analysis(id)
    except psycopg.Error:
        return{
            "status":"error",
            "analysis":None,
            "error": {
                "code": "DATABASE_ERROR",
                "message": "无法查询飞行分析记录"
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
            "analysis_id":data["id"],
            "filename":data["filename"],
            "summary":{
                "row_count":data["row_count"],
                "max_speed":data["max_speed"],
                "max_temperature":data["max_temperature"],
                "minimum_battery":data["minimum_battery"]
            }
        }
    }