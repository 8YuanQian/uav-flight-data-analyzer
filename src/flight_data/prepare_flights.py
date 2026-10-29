"""Validate CSV intervals and calculate one database row per flight group."""

import re
from datetime import datetime, timedelta, timezone

import pandas as pd

from .analyze_data import calculate_summary, detect_anomalies_dataframe
from .clean_data import clean_data


REQUIRED_COLUMNS = {
    "uav_code", "uav_model", "manufacturer", "flight_id",
    "start_time", "end_time", "height", "speed", "battery", "temperature",
}
TIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
LOCAL_TIMEZONE = timezone(timedelta(hours=8))
REPORT_FIELDS = (
    "row_count", "average_height", "average_speed", "average_temperature",
    "max_height", "max_speed", "max_temperature", "minimum_battery",
)


def _parse_time(value, column, row_number):
    if not isinstance(value, str) or not TIME_PATTERN.fullmatch(value):
        raise ValueError(f"第 {row_number} 行 {column} 必须为 YYYY-MM-DD HH:mm")
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=LOCAL_TIMEZONE)
    except ValueError as exc:
        raise ValueError(f"第 {row_number} 行 {column} 不是有效日期时间") from exc


def prepare_flights(data: pd.DataFrame) -> list[dict]:
    """Keep CSV flight_id only in the returned group metadata; never persist it."""
    missing = REQUIRED_COLUMNS - set(data.columns)
    if missing:
        raise ValueError(f"Missing required columns {sorted(missing)}")
    if data.empty:
        raise ValueError("CSV 没有数据行")

    frame = data.copy()
    for column in ("uav_code", "uav_model", "manufacturer", "flight_id"):
        frame[column] = frame[column].astype("string").str.strip()
        if frame[column].isna().any() or frame[column].eq("").any():
            raise ValueError(f"{column} 不能为空")

    frame["start_time"] = [
        _parse_time(value, "start_time", index + 2)
        for index, value in enumerate(frame["start_time"])
    ]
    frame["end_time"] = [
        _parse_time(value, "end_time", index + 2)
        for index, value in enumerate(frame["end_time"])
    ]
    if (frame["end_time"] <= frame["start_time"]).any():
        raise ValueError("每行 end_time 必须晚于 start_time")

    # One code must describe one model and manufacturer throughout this upload.
    for uav_code, rows in frame.groupby("uav_code", sort=False, dropna=False):
        if rows["uav_model"].nunique() != 1 or rows["manufacturer"].nunique() != 1:
            raise ValueError(f"飞行器 {uav_code} 的型号或制造商不一致")

    result = []
    for (uav_code, flight_id), rows in frame.groupby(
        ["uav_code", "flight_id"], sort=False, dropna=False
    ):
        rows = rows.sort_values(["start_time", "end_time"], kind="stable").copy()
        previous_end = rows["end_time"].shift()
        if (rows["start_time"] < previous_end).fillna(False).any():
            raise ValueError(f"飞行 {flight_id} 的时间区间重叠")

        try:
            cleaned = clean_data(rows)
        except ValueError as exc:
            raise ValueError(f"飞行 {flight_id}: {exc}") from exc
        summary = calculate_summary(cleaned)
        anomalies = detect_anomalies_dataframe(cleaned)
        reasons = []
        if not anomalies["low_battery"].empty:
            reasons.append("低电量")
        if not anomalies["high_speed_temperature"].empty:
            reasons.append("高速度且高温度")

        started = cleaned["start_time"].iloc[0]
        ended = cleaned["end_time"].max()
        result.append({
            "csv_flight_id": str(flight_id),  # Response mapping only, not a database column.
            "uav_code": str(uav_code),
            "uav_model": str(cleaned["uav_model"].iloc[0]),
            "manufacturer": str(cleaned["manufacturer"].iloc[0]),
            "start_time": started,
            "end_time": ended,
            "duration_minutes": round((ended - started).total_seconds() / 60, 2),
            "battery_start": round(float(cleaned["battery"].iloc[0]), 2),
            "battery_end": round(float(cleaned["battery"].iloc[-1]), 2),
            "anomaly_status": "warning" if reasons else "normal",
            "anomaly_reason": "、".join(reasons) if reasons else None,
            **summary,
        })
    return result
