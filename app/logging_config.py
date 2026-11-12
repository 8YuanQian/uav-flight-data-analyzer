# 为 API 和 Celery worker 提供按北京时间分日的文件日志。

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from celery.signals import after_setup_logger, after_setup_task_logger


LOG_TIMEZONE = timezone(timedelta(hours=8))
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


class BeijingFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        # 文件名和日志时间都按北京时间计算，避免跨零点时写入错误的日期文件。
        timestamp = datetime.fromtimestamp(record.created, LOG_TIMEZONE)
        if datefmt:
            return timestamp.strftime(datefmt)
        return timestamp.strftime("%Y-%m-%d %H:%M:%S") + f".{timestamp.microsecond // 1000:03d}+08:00"


class DailyFileHandler(logging.Handler):
    def __init__(self, directory: Path, prefix: str):
        super().__init__(level=logging.INFO)
        self.directory = Path(directory)
        self.prefix = prefix
        self.directory.mkdir(parents=True, exist_ok=True)

    def emit(self, record):
        # 每条日志按事件日期选择文件；worker 父子进程无需共同执行文件重命名。
        day = datetime.fromtimestamp(record.created, LOG_TIMEZONE).strftime("%Y-%m-%d")
        try:
            data = (self.format(record) + "\n").encode("utf-8")
        except Exception:
            self.handleError(record)
            return
        # 只写当前项目的日志目录，不把日志同步到其他项目。
        path = self.directory / f"{self.prefix}-{day}.log"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            try:
                remaining = data
                while remaining:
                    written = os.write(fd, remaining)
                    if written == 0:
                        raise OSError("日志文件写入失败")
                    remaining = remaining[written:]
            finally:
                os.close(fd)
        except Exception:
            self.handleError(record)


def _log_directory(service: str) -> Path:
    # 显式配置的是最终目录；容器通过不同挂载将 /app/logs 分别映射到四个目录。
    configured = os.getenv("UAV_LOG_DIR")
    if configured:
        return Path(configured)
    # 宿主机运行时也区分服务，连接测试库的进程使用 test_ 前缀。
    prefix = "test_" if os.getenv("UAV_DB_NAME") == "uav_project_test" else ""
    return Path(__file__).resolve().parents[1] / "logs" / f"{prefix}{service}"


def create_api_file_handler() -> DailyFileHandler:
    return DailyFileHandler(_log_directory("fastapi"), "fastapi")


def _attach_worker_file_handler(logger, **kwargs):
    # Celery 的普通日志和任务日志分别配置，后者默认不会向根 logger 传播。
    if any(isinstance(handler, DailyFileHandler) and handler.prefix == "worker"
           for handler in logger.handlers):
        return
    handler = DailyFileHandler(_log_directory("worker"), "worker")
    handler.setFormatter(BeijingFormatter(LOG_FORMAT))
    logger.addHandler(handler)


def register_worker_logging() -> None:
    # Celery 初始化 logger 后再挂载文件 handler，避免被 Celery 的默认配置清除。
    after_setup_logger.connect(_attach_worker_file_handler, weak=False)
    after_setup_task_logger.connect(_attach_worker_file_handler, weak=False)
