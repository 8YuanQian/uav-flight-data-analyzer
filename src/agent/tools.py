from src.database import get_connection
from src.retrieve import retrieve
from src.reranker import rerank_documents
from src.model import create_transformat_model 

import psycopg
import json


def get_flight_data(limit:int=1,flight_id:str="SIM-FLIGHT-0001")->list[dict]:
    if flight_id == None:
        flight_id = "SIM-FLIGHT-0001"
        
    with get_connection() as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            cursor.execute(
                """SELECT * FROM flight_records WHERE created_at >= (SELECT MIN(created_at) FROM flight_records WHERE flight_id = %s) ORDER BY created_at DESC LIMIT %s""",
                (flight_id,limit)
            )
            data = cursor.fetchall()
    return data


def analyze_flight_data(limit:int = 1,flight_id:str | None = None)->dict:
    """
    分析无人机飞行数据，
    检测高度、速度、电池、温度异常。
    """

    with get_connection() as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            if flight_id:
                cursor.execute(
                    """
                    SELECT * FROM flight_records WHERE flight_id = %s ORDER BY created_at DESC LIMIT %s
                    """,
                    (
                        flight_id,limit
                    )
                )
            else:
                cursor.execute(
                    """
                    SELECT * FROM flight_records ORDER BY created_at DESC LIMIT %s
                    """,
                    (limit,)
                )
            flights = cursor.fetchall()

    if not flights:
        return {
            "status":"failed",
            "message":"没有找到飞行记录"
        }

    results=[]
    for flight in flights:
        risk_score=0
        warnings=[]

        # ---------- 电池分析 ----------

        battery_used = (flight["battery_start"] - flight["battery_end"])
        battery_rate = (battery_used /flight["duration_seconds"])
        if battery_used > 70:
            risk_score += 20
            warnings.append("电池消耗过大")

        # ---------- 高度分析 ----------

        if flight["max_height"] > 120:
            risk_score += 20
            warnings.append("最大飞行高度超过限制")

        if flight["average_height"] < 10:
            risk_score +=10
            warnings.append("平均飞行高度异常偏低")

        # ---------- 速度分析 ----------

        if flight["max_speed"] > 25:
            risk_score +=15
            warnings.append("存在高速飞行风险")

        # ---------- 温度分析 ----------

        if flight["average_temperature"] >45:
            risk_score +=25
            warnings.append("平均温度过高")

        # ---------- 风险等级 ----------

        if risk_score < 30:
            level="normal"
        elif risk_score <60:
            level="warning"
        else:
            level="danger"

        results.append({
            "flight_id":flight["flight_id"],
            "drone_id":flight["drone_id"],
            "risk_score":risk_score,
            "risk_level":level,
            "battery_analysis":{
                "used":round(battery_used,2),
                "rate":round(battery_rate,4)
            },

            "performance":{
                "average_height":flight["average_height"],
                "max_height":flight["max_height"],
                "average_speed":flight["average_speed"],
                "max_speed":flight["max_speed"]
            },
            "warnings":warnings
        })

    return {
        "status":"success",
        "analysis":results
    }
    

def rag_search(query:str)->list[dict]:
    model = create_transformat_model()
    retrieve_data = retrieve(query=query,embedding_model=model["embedding_model"])
    rerank_data = rerank_documents(query=query,documents=retrieve_data,rerank_model=model["rerank_model"])
    return rerank_data 





