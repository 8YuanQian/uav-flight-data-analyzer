# 用户编号只能来自已验证身份或数据库中的任务归属。
from contextlib import contextmanager
from contextvars import ContextVar

_data_user: ContextVar[int | None] = ContextVar("flight_data_user", default=None)


def require_data_user_id() -> int:
    user_id = _data_user.get()
    if type(user_id) is not int or user_id <= 0:
        raise PermissionError("访问飞行数据前必须确认用户身份")
    return user_id


@contextmanager
def use_data_user(user_id: int):
    if type(user_id) is not int or user_id <= 0:
        raise PermissionError("任务或请求缺少有效用户归属")
    token = _data_user.set(user_id)
    try:
        yield
    finally:
        # 还原上下文，防止线程复用时串用其他用户身份。
        _data_user.reset(token)
