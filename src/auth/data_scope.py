# 用户编号只能来自已验证身份或数据库中的任务归属。
from contextlib import contextmanager
from contextvars import ContextVar

_data_user: ContextVar[int | None] = ContextVar("flight_data_user", default=None)
_data_user_jwt: ContextVar[str | None] = ContextVar("flight_data_user_jwt", default=None)


def require_data_user_id() -> int:
    user_id = _data_user.get()
    if type(user_id) is not int or user_id <= 0:
        raise PermissionError("访问飞行数据前必须确认用户身份")
    return user_id


def require_data_user_jwt() -> str:
    jwt_token = _data_user_jwt.get()
    if not isinstance(jwt_token, str) or not jwt_token:
        raise PermissionError("当前用户上下文缺少登录凭证")
    return jwt_token


@contextmanager
def use_data_user(user_id: int, jwt_token: str | None = None):
    if type(user_id) is not int or user_id <= 0:
        raise PermissionError("任务或请求缺少有效用户归属")
    if jwt_token is not None and (not isinstance(jwt_token, str) or not jwt_token.strip()):
        raise PermissionError("登录凭证必须是非空字符串")
    # 这里只绑定身份和凭证，JWT 的真实性由登录入口及安全节点验证。
    # worker 按任务归属绑定用户时没有浏览器 JWT，明确设置为 None，避免继承其他身份的凭证。
    user_marker = _data_user.set(user_id)
    jwt_marker = _data_user_jwt.set(jwt_token)
    try:
        yield
    finally:
        # 正常结束、异常退出和嵌套调用都成对恢复，避免串用身份或凭证。
        try:
            _data_user_jwt.reset(jwt_marker)
        finally:
            _data_user.reset(user_marker)
