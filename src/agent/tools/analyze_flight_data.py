from src.database.flight_record_repository import get_flight_by_id, get_recent_flights


def analyze_flight_data(
    limit: int = 1, record_id: int | None = None, uav_code: str | None = None
) -> dict:
    """
    分析无人机飞行数据，
    检测高度、速度、电池、温度异常。
    """

    if record_id is not None:
        flight = get_flight_by_id(record_id)
        flights = [flight] if flight is not None else []
    else:
        flights = get_recent_flights(limit, uav_code)

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
        battery_rate = battery_used / float(flight["duration_minutes"])
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
            "record_id":flight["id"],
            "uav_code":flight["uav_code"],
            "risk_score":risk_score,
            "risk_level":level,
            "battery_analysis":{
                "used":round(battery_used,2),
                "rate_per_minute":round(battery_rate,4)
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
