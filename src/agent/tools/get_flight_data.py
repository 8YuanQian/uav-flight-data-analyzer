"""Read new flight records by database id or UAV code."""

from src.database.flight_record_repository import get_flight_by_id, get_recent_flights


def get_flight_data(
    limit: int = 1, record_id: int | None = None, uav_code: str | None = None, uav_id: int | None = None
) -> list[dict]:
    if record_id is not None:
        record = get_flight_by_id(record_id)
        return [record] if record is not None else []
    return get_recent_flights(limit or 1, uav_code, uav_id=uav_id) if uav_id is not None else get_recent_flights(limit or 1, uav_code)
