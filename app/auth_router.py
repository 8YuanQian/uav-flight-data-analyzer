# 注册、登录及退出登录的页面和接口。

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from src.auth.security import AuthIdentity, InvalidAccessToken, hash_password, issue_access_token, verify_password
from src.database.user_repository import UsernameAlreadyExists, create_user, find_login_user

from .auth_dependencies import COOKIE_NAME, identity_from_request
from .database_dependency import database_pool_for_route


auth_router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# 根据登录 Cookie 是否有效，将访客和已登录用户送到对应页面。
@auth_router.get("/", include_in_schema=False)
def home(request: Request):
    try:
        identity_from_request(request)
    except InvalidAccessToken:
        return RedirectResponse("/login", status_code=303)
    return RedirectResponse("/chats", status_code=303)


@auth_router.get("/register", include_in_schema=False)
def register_page(request: Request):
    return templates.TemplateResponse(request, "register.html")


@auth_router.post("/auth/register", dependencies=[Depends(database_pool_for_route)])
def register(request: Request, username: str = Form(), password: str = Form()):
    # 用户名去掉首尾空白；密码保持用户原样输入，交给哈希函数处理。
    username = username.strip()
    if not username or not password:
        return templates.TemplateResponse(request, "register.html", {"error": "用户名和密码不能为空", "username": username}, status_code=422)
    try:
        # 仓储层在同一事务中创建用户和密码行，数据库不接收明文密码。
        create_user(username, hash_password(password))
    except UsernameAlreadyExists:
        return templates.TemplateResponse(request, "register.html", {"error": "用户名已存在", "username": username}, status_code=409)
    return RedirectResponse("/login?registered=1", status_code=303)


@auth_router.get("/login", include_in_schema=False)
def login_page(request: Request, registered: bool = False):
    return templates.TemplateResponse(request, "login.html", {"registered": registered})


@auth_router.post("/auth/login", dependencies=[Depends(database_pool_for_route)])
def login(request: Request, username: str = Form(), password: str = Form()):
    username = username.strip()
    user = find_login_user(username) if username else None
    if user is None:
        return templates.TemplateResponse(request, "login.html", {"error": "用户名输入错误或用户名不存在", "username": username}, status_code=401)
    if not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse(request, "login.html", {"error": "密码输入错误", "username": username}, status_code=401)

    # JWT 仅标识用户；会话归属要在后续查询时重新向数据库核验。
    token = issue_access_token(AuthIdentity(user_id=user["id"], user_name=user["username"]))
    # 303 使浏览器跳转后使用 GET 打开列表页，避免刷新时重复提交登录表单。
    response = RedirectResponse("/chats", status_code=303)
    # HttpOnly 禁止页面脚本读取令牌；HTTPS 下再启用 Secure 属性。
    response.set_cookie(
        COOKIE_NAME, token, max_age=3600, httponly=True,
        secure=request.url.scheme == "https", samesite="lax", path="/",
    )
    return response


@auth_router.post("/auth/logout", include_in_schema=False)
def logout():
    # 删除浏览器 Cookie；无服务端撤销列表的 JWT 会在原定到期时失效。
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response
