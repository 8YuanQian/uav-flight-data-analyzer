"""只为可能访问数据库的 FastAPI 路由提供连接池。"""

from fastapi import Request

from src.database.connection import use_request_pool


async def database_pool_for_route(request: Request):
    # 这里只绑定池；真正执行 get_connection() 时才申请连接。
    with use_request_pool(request.app.state.db_pool):
        yield
