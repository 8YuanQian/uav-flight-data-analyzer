import os
from contextlib import contextmanager
from contextvars import ContextVar

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolClosed, PoolTimeout

PASSWORD = os.getenv("PASSWORD")
DB_NAME = os.getenv("UAV_DB_NAME","uav_project")
HOST = os.getenv("UAV_DB_HOST", "localhost")
PORT = os.getenv("UAV_DB_PORT", os.getenv("PORT", 5433))

POOL_MIN_SIZE = 2
API_POOL_MAX_SIZE = 5
WORKER_POOL_MAX_SIZE = 15
POOL_TIMEOUT_SECONDS = 60

_request_pool: ContextVar[ConnectionPool | None] = ContextVar(
    "request_database_pool", default=None
)
_worker_pool: ConnectionPool | None = None


class DatabasePoolError(RuntimeError):
    """向数据库连接池申请连接时发生的错误。"""


class DatabaseConnectionTimeout(DatabasePoolError):
    """等待池连接超过设定时间。"""


class DatabasePoolUnavailable(DatabasePoolError):
    """连接池已关闭。"""


def create_connection_pool(max_size: int, name: str) -> ConnectionPool:
    """创建池但暂不打开；调用方负责管理打开和关闭。"""
    return ConnectionPool(
        kwargs={
            "host": HOST,
            "port": PORT,
            "dbname": DB_NAME,
            "user": "postgres",
            "password": PASSWORD,
        },
        min_size=POOL_MIN_SIZE,
        max_size=max_size,
        timeout=POOL_TIMEOUT_SECONDS,
        name=name,
        open=False,
    )


def create_checkpoint_pool() -> ConnectionPool:
    """为 LangGraph 检查点单独建池，避免改变业务连接的事务设置。"""
    return ConnectionPool(
        kwargs={
            "host": HOST,
            "port": PORT,
            "dbname": DB_NAME,
            "user": "postgres",
            "password": PASSWORD,
            "autocommit": True,
            "row_factory": dict_row,
        },
        min_size=1,
        max_size=2,
        timeout=POOL_TIMEOUT_SECONDS,
        name="uav-checkpoint",
        open=False,
    )


@contextmanager
def use_request_pool(pool: ConnectionPool):
    """把 API 池提供给当前路由，暂不借出数据库连接。"""
    token = _request_pool.set(pool)
    try:
        yield
    finally:
        _request_pool.reset(token)


@contextmanager
def _pooled_connection(pool: ConnectionPool):
    """实际访问数据库时才借连接，退出仓储函数时归还。"""
    try:
        with pool.connection(timeout=POOL_TIMEOUT_SECONDS) as connection:
            yield connection
    except PoolTimeout as exc:
        raise DatabaseConnectionTimeout from exc
    except PoolClosed as exc:
        raise DatabasePoolUnavailable from exc


def open_worker_pool() -> None:
    """在 Celery 子进程内打开它自己的连接池。"""
    global _worker_pool
    if _worker_pool is None:
        pool = create_connection_pool(WORKER_POOL_MAX_SIZE, "uav-worker")
        pool.open(wait=False)
        _worker_pool = pool


def close_worker_pool() -> None:
    global _worker_pool
    pool = _worker_pool
    _worker_pool = None
    if pool is not None:
        pool.close()


def get_connection():
    """按需借用 API 或 worker 池连接；独立脚本保持原连接方式。"""
    pool = _request_pool.get()
    if pool is not None:
        return _pooled_connection(pool)
    if _worker_pool is not None:
        return _pooled_connection(_worker_pool)
    return psycopg.connect(host=HOST,port=PORT,dbname=DB_NAME,user="postgres",password=PASSWORD)
