# 从 API Bearer 令牌或浏览器 Cookie 中读取已签名的用户身份。

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.security.utils import get_authorization_scheme_param

from src.auth.security import AuthIdentity, InvalidAccessToken, read_access_token
from src.auth.data_scope import use_data_user


COOKIE_NAME = "uav_access_token"
# 允许没有 Authorization 头：浏览器页面会改从 HttpOnly Cookie 读取 JWT。
_bearer = HTTPBearer(auto_error=False)


# API 优先读取 Bearer 令牌；普通浏览器请求读取登录 Cookie。
def jwt_from_request(request: Request, bearer: HTTPAuthorizationCredentials | None = None) -> str | None:
    if bearer is not None:
        return bearer.credentials
    scheme, credentials = get_authorization_scheme_param(request.headers.get("Authorization"))
    if scheme.lower() == "bearer" and credentials:
        return credentials
    return request.cookies.get(COOKIE_NAME)


def identity_from_request(request: Request, bearer: HTTPAuthorizationCredentials | None = None) -> AuthIdentity:
    token = jwt_from_request(request, bearer)
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


async def user_data_scope(request: Request, user: AuthIdentity = Depends(require_user)):
    # 异步依赖中绑定本次请求的身份和 JWT，供后续同步路由读取。
    with use_data_user(user.user_id, jwt_from_request(request)):
        yield user
