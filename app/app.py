import os
from contextlib import asynccontextmanager

from celery import Celery
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import PoolClosed, PoolTimeout
from redis import Redis
from sentence_transformers import CrossEncoder, SentenceTransformer

from src.agent.graph.graph import build_graph
from src.database.connection import (
    API_POOL_MAX_SIZE,
    DatabaseConnectionTimeout,
    DatabasePoolError,
    create_checkpoint_pool,
    create_connection_pool,
)

from .ai_router import ai_flight_router
from .flight_data_router import flight_router


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    rerank_model = CrossEncoder("BAAI/bge-reranker-base")
    embedding_model = SentenceTransformer("intfloat/multilingual-e5-base")
    fastapi_app.state.embedding_model = embedding_model
    # 应用启动时创建一次客户端供各请求复用；Redis /2 专放业务数据缓存。
    fastapi_app.state.cache = Redis.from_url(
        os.getenv("REDIS_CACHE_URL", "redis://redis:6379/2"),
        decode_responses=True,
        socket_connect_timeout=0.3,
        socket_timeout=0.3,
    )
    # 只有绑定数据库依赖的路由会使用此池，且在实际查询时才借连接。
    fastapi_app.state.db_pool = create_connection_pool(API_POOL_MAX_SIZE, "uav-api")
    # 检查点使用 autocommit 和 dict_row，不能直接复用业务连接池。
    checkpoint_pool = create_checkpoint_pool()
    try:
        fastapi_app.state.db_pool.open(wait=False)
        checkpoint_pool.open(wait=True)
        checkpointer = PostgresSaver(checkpoint_pool)
        # setup 会创建或升级检查点表；重复启动时会跳过已完成的迁移。
        checkpointer.setup()
        fastapi_app.state.agent_graph = build_graph(
            embedding_model=embedding_model,
            rerank_model=rerank_model,
            checkpointer=checkpointer,
        )
        yield
    finally:
        try:
            checkpoint_pool.close()
        finally:
            try:
                fastapi_app.state.db_pool.close()
            finally:
                # FastAPI 关闭时释放客户端管理的连接。
                fastapi_app.state.cache.close()
        print("free resource")


async def database_pool_error_handler(
    request: Request, exc: DatabasePoolError | PoolClosed | PoolTimeout
):
    if isinstance(exc, (DatabaseConnectionTimeout, PoolTimeout)):
        detail = "等待数据库连接超过 60 秒，请稍后重试"
    else:
        detail = "数据库连接池不可用，请稍后重试"
    return JSONResponse(status_code=503, content={"detail": detail})


def create_fastapi_app() -> FastAPI:
    fastapi_app = FastAPI(lifespan=lifespan)
    fastapi_app.add_exception_handler(DatabasePoolError, database_pool_error_handler)
    fastapi_app.add_exception_handler(PoolTimeout, database_pool_error_handler)
    fastapi_app.add_exception_handler(PoolClosed, database_pool_error_handler)
    fastapi_app.include_router(ai_flight_router)
    fastapi_app.include_router(flight_router)
    return fastapi_app


def create_celery_app() -> Celery:
    broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
    result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")
    return Celery("uav_project", broker=broker_url, backend=result_backend, include=["app.tasks"])


app = create_fastapi_app()
celery_app = create_celery_app()
app.state.celery_app = celery_app
