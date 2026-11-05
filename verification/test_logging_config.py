import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.logging_config import (
    BeijingFormatter, DailyFileHandler, LOG_FORMAT,
    create_api_file_handler, _attach_worker_file_handler,
)


def test_api_and_worker_logs_are_separated_by_service_and_beijing_date(tmp_path):
    api_logger = logging.Logger("test.api", level=logging.INFO)
    worker_logger = logging.Logger("test.worker", level=logging.INFO)
    for logger, prefix in ((api_logger, "fastapi"), (worker_logger, "worker")):
        handler = DailyFileHandler(tmp_path, prefix)
        handler.setFormatter(BeijingFormatter(LOG_FORMAT))
        logger.addHandler(handler)

    # UTC 15:59 和 16:00 分别对应北京时间当天 23:59 和次日 00:00。
    before = datetime(2026, 10, 29, 15, 59, tzinfo=timezone.utc).timestamp()
    after = datetime(2026, 10, 29, 16, 0, tzinfo=timezone.utc).timestamp()
    for logger in (api_logger, worker_logger):
        for timestamp, message in ((before, "昨天"), (after, "今天")):
            record = logger.makeRecord(logger.name, logging.INFO, __file__, 1, message, (), None)
            record.created = timestamp
            logger.handle(record)

    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "fastapi-2026-10-29.log",
        "fastapi-2026-10-30.log",
        "worker-2026-10-29.log",
        "worker-2026-10-30.log",
    ]
    assert "昨天" in (tmp_path / "fastapi-2026-10-29.log").read_text(encoding="utf-8")
    assert "今天" not in (tmp_path / "fastapi-2026-10-29.log").read_text(encoding="utf-8")
    assert "test.worker" not in (tmp_path / "fastapi-2026-10-29.log").read_text(encoding="utf-8")
    assert "test.worker" in (tmp_path / "worker-2026-10-29.log").read_text(encoding="utf-8")


def test_api_and_worker_only_write_their_own_project(monkeypatch, tmp_path):
    primary, mirror = tmp_path / "primary", tmp_path / "original"
    monkeypatch.setenv("UAV_LOG_DIR", str(primary))
    monkeypatch.setenv("UAV_LOG_MIRROR_DIR", str(mirror))
    api_logger = logging.Logger("mirror.api", level=logging.INFO)
    handler = create_api_file_handler()
    handler.setFormatter(BeijingFormatter(LOG_FORMAT))
    api_logger.addHandler(handler)
    worker_logger = logging.Logger("mirror.worker", level=logging.INFO)
    _attach_worker_file_handler(worker_logger)
    _attach_worker_file_handler(worker_logger)

    api_logger.info("API 副本测试")
    worker_logger.info("worker 副本测试")
    api_logger.debug("不应保存 DEBUG")

    assert len(worker_logger.handlers) == 1
    assert len(list(primary.glob("*.log"))) == 2
    assert not mirror.exists()
    for path in primary.glob("*.log"):
        assert "DEBUG" not in path.read_text(encoding="utf-8")


def test_same_directory_is_not_written_twice(tmp_path):
    handler = DailyFileHandler(tmp_path, "fastapi")
    logger = logging.Logger("same-directory", level=logging.INFO)
    logger.addHandler(handler)
    logger.info("唯一一条")
    assert next(tmp_path.glob("*.log")).read_text(encoding="utf-8").count("唯一一条") == 1


def test_log_write_failure_is_reported(monkeypatch, tmp_path):
    import app.logging_config as config
    primary = tmp_path / "primary"
    handler = DailyFileHandler(primary, "fastapi")
    error = MagicMock()
    monkeypatch.setattr(handler, "handleError", error)
    monkeypatch.setattr(config.os, "open", MagicMock(side_effect=OSError("目录不可写")))
    logger = logging.Logger("mirror-failure", level=logging.INFO)
    logger.addHandler(handler)
    logger.info("主日志必须保存")

    assert not list(primary.glob("*.log"))
    error.assert_called_once()
