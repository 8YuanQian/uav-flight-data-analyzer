# 从 API Bearer 令牌或浏览器 Cookie 中读取已签名的用户身份。

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.auth.security import AuthIdentity, InvalidAccessToken, read_access_token
from src.auth.data_scope import use_data_user


COOKIE_NAME = "uav_access_token"
# 允许没有 Authorization 头：浏览器页面会改从 HttpOnly Cookie 读取 JWT。
_bearer = HTTPBearer(auto_error=False)


# API 优先读取 Bearer 令牌；普通浏览器请求读取登录 Cookie。
def identity_from_request(request: Request, bearer: HTTPAuthorizationCredentials | None = None) -> AuthIdentity:
    token = bearer.credentials if bearer else request.cookies.get(COOKIE_NAME)
    if not token:
        raise InvalidAccessToken("请先登录")
    return read_access_token(token)


# 供受保护接口注入用户身份；令牌缺失或失效时统一返回 401。
def require_user(
    request: Request,
    bearer: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthIdentity:
    try:
        return identity_from_request(request, bearer)
    except InvalidAccessToken as exc:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录") from exc


async def user_data_scope(user: AuthIdentity = Depends(require_user)):
    # 将已验证身份传到同步路由和其调用的仓储层。
    with use_data_user(user.user_id):
        yield user
