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
    """Records were committed, but at least one AI report could not be generated."""

    def __init__(self, record_ids: list[int]):
        self.record_ids = record_ids
        super().__init__(record_ids)


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
