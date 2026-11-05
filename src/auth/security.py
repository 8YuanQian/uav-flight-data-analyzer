# 处理密码哈希和短期有效的登录令牌。

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError


# JWT 和浏览器 Cookie 都以一小时为有效期；校验时只接受指定签名算法。
TOKEN_LIFETIME = timedelta(hours=1)
DELETE_CONFIRMATION_LIFETIME = timedelta(minutes=5)
TOKEN_ALGORITHM = "HS256"
# Argon2 会为每次哈希使用独立盐值，数据库只保存生成后的哈希。
_password_hasher = PasswordHasher()


# 保存从有效 JWT 中解析出的用户身份；会话 ID 不放进 JWT。
@dataclass(frozen=True)
class AuthIdentity:
    user_id: int
    user_name: str


# Cookie 或 Bearer 令牌无法通过校验时抛出此异常。
class InvalidAccessToken(ValueError):
    pass


# 注册时生成要写入 password 表的哈希。
def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


# 登录时比对输入与存储的哈希；损坏的哈希视为校验失败。
def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return _password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerificationError):
        return False


def _token_secret() -> str:
    # 签名密钥只从环境变量读取；长度不足时阻止签发和校验 JWT。
    secret = os.getenv("JWT_SECRET_KEY", "")
    if len(secret) < 32:
        raise RuntimeError("JWT_SECRET_KEY must contain at least 32 characters")
    return secret


# 在 API 启动时检查签名密钥，避免用户登录时才发现配置错误。
def validate_token_config() -> None:
    _token_secret()


# 签发 JWT：只写用户身份、签发时间和过期时间。
def issue_access_token(identity: AuthIdentity) -> str:
    issued_at = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "user_id": identity.user_id,
            "user_name": identity.user_name,
            "iat": issued_at,
            "exp": issued_at + TOKEN_LIFETIME,
        },
        _token_secret(),
        algorithm=TOKEN_ALGORITHM,
    )


# 先验证签名、算法和有效期，再读取可信的用户身份。
def read_access_token(token: str) -> AuthIdentity:
    try:
        claims = jwt.decode(
            token,
            _token_secret(),
            algorithms=[TOKEN_ALGORITHM],
            options={"require": ["user_id", "user_name", "iat", "exp"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidAccessToken("Invalid or expired access token") from exc

    # 拒绝布尔值、非正数 ID 或空用户名，避免形状错误的载荷进入业务层。
    user_id = claims.get("user_id")
    user_name = claims.get("user_name")
    if type(user_id) is not int or user_id <= 0 or not isinstance(user_name, str) or not user_name.strip():
        raise InvalidAccessToken("Invalid access token identity")
    return AuthIdentity(user_id=user_id, user_name=user_name)


# 为确认页面签发短期令牌，并绑定当前用户、单个会话及删除操作。
def issue_delete_confirmation(identity: AuthIdentity, thread_id: UUID) -> str:
    issued_at = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "action": "delete_chat",
            "user_id": identity.user_id,
            "thread_id": str(thread_id),
            "iat": issued_at,
            "exp": issued_at + DELETE_CONFIRMATION_LIFETIME,
        },
        _token_secret(),
        algorithm=TOKEN_ALGORITHM,
    )


# 仅接受确认页面签发且仍有效的令牌；普通登录令牌不能代替删除确认。
def verify_delete_confirmation(token: str, identity: AuthIdentity, thread_id: UUID) -> bool:
    try:
        claims = jwt.decode(
            token,
            _token_secret(),
            algorithms=[TOKEN_ALGORITHM],
            options={"require": ["action", "user_id", "thread_id", "iat", "exp"]},
        )
    except jwt.PyJWTError:
        return False
    return (
        claims["action"] == "delete_chat"
        and type(claims["user_id"]) is int
        and claims["user_id"] == identity.user_id
        and claims["thread_id"] == str(thread_id)
    )
