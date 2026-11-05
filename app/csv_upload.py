"""Stage CSV uploads in a directory shared by the API and Celery worker."""

import os
import re
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4


class CsvValidationError(ValueError):
    """The uploaded CSV cannot be parsed or prepared for import."""


class CsvCacheError(RuntimeError):
    """Records were committed, but their list caches could not be cleared."""

    def __init__(self, record_ids: list[int]):
        self.record_ids = record_ids
        super().__init__(record_ids)


class CsvReportError(RuntimeError):
    # 报告生成发生在入库前；失败时只标识对应的 CSV 飞行分组。

    def __init__(self, uav_code: str, csv_flight_id: str):
        self.uav_code = uav_code
        self.csv_flight_id = csv_flight_id
        super().__init__(uav_code, csv_flight_id)


def staged_csv_path(upload_id: str) -> Path:
    """Accept only generated IDs, never a client-supplied filesystem path."""
    if re.fullmatch(r"[0-9a-f]{32}", upload_id) is None:
        raise ValueError("Invalid CSV upload ID")
    directory = Path(os.getenv("CSV_UPLOAD_DIR", Path(tempfile.gettempdir()) / "uav_csv_uploads"))
    return directory / f"{upload_id}.csv"


def stage_csv_upload(file_object) -> str:
    """Copy the upload to shared storage before publishing the task."""
    upload_id = uuid4().hex
    path = staged_csv_path(upload_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as staged:
            shutil.copyfileobj(file_object, staged)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return upload_id
