"""Read new flight records by database id or UAV code."""

from src.database.flight_record_repository import (
    get_flight_by_id, get_flights_from_flight_id, get_flights_from_record, get_recent_flights,
)


def get_flight_data(
    limit: int = 1, record_id: int | None = None, flight_id: str | None = None,
    uav_code: str | None = None, uav_id: int | None = None, *, user_id: int,
) -> list[dict]:
    # flight_id 是 CSV 提供的编号；record_id 是数据库生成的编号，两者不能同时指定。
    if flight_id is not None:
        if record_id is not None:
            raise ValueError("flight_id 和 record_id 不能同时指定")
        return get_flights_from_flight_id(flight_id, limit, user_id=user_id)
    if record_id is not None:
        if limit > 1:
            return get_flights_from_record(record_id, limit, user_id=user_id)
        record = get_flight_by_id(record_id, user_id=user_id)
        return [record] if record is not None else []
    return get_recent_flights(limit, uav_code, uav_id=uav_id, user_id=user_id)
