# 用替身验证浏览器登录和会话归属，不访问真实数据库、Redis 或大模型。

from datetime import datetime, timezone
import re
from types import SimpleNamespace
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ai_router import ai_flight_router
from app.auth_dependencies import COOKIE_NAME
from app.auth_router import auth_router
from app.chat_router import chat_router
from app.database_dependency import database_pool_for_route
from src.auth.security import AuthIdentity, InvalidAccessToken, hash_password, issue_access_token, issue_delete_confirmation, read_access_token, validate_token_config


# 模拟检查点和两轮消息累积，不调用真实模型或数据库。
class FakeGraph:
    def __init__(self):
        self.states = {}

    def get_state(self, config):
        return SimpleNamespace(values=self.states.get(config["configurable"]["thread_id"], {}))

    def invoke(self, initial, config):
        thread_id = config["configurable"]["thread_id"]
        previous = self.states.get(thread_id, {"message": []})
        messages = previous["message"] + [{"role": "user", "content": initial["query"]}]
        answer = {"answer": f"回答：{initial['query']}", "sources": []}
        messages.append({"role": "assistant", "content": answer})
        self.states[thread_id] = {"message": messages}
        return {"answer": answer}


def test_token_claims_expire_after_one_hour(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "a" * 40)
    token = issue_access_token(AuthIdentity(7, "Bob"))
    claims = jwt.decode(token, "a" * 40, algorithms=["HS256"])
    assert set(claims) == {"user_id", "user_name", "iat", "exp"}
    assert claims["exp"] - claims["iat"] == 3600
    assert read_access_token(token) == AuthIdentity(7, "Bob")
    assert datetime.fromtimestamp(claims["iat"], timezone.utc).tzinfo is not None

    expired = jwt.encode({"user_id": 7, "user_name": "Bob", "iat": 1, "exp": 2}, "a" * 40, algorithm="HS256")
    with pytest.raises(InvalidAccessToken):
        read_access_token(expired)


def test_missing_signing_secret_fails_at_startup(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        validate_token_config()


def test_register_login_chat_and_existing_api_ownership(monkeypatch):
    # 仓储函数使用内存替身，专门检查 HTTP 流程与会话授权边界。
    monkeypatch.setenv("JWT_SECRET_KEY", "b" * 40)
    legacy_thread_id = uuid4()
    titles = {}
    users = {
        "Bob": {"id": 1, "username": "Bob", "password_hash": hash_password("123456"), "threads": [legacy_thread_id]},
        "Alice": {"id": 2, "username": "Alice", "password_hash": hash_password("123456"), "threads": []},
    }

    def create_user(username, password_hash):
        if any(existing.lower() == username.lower() for existing in users):
            from src.database.user_repository import UsernameAlreadyExists
            raise UsernameAlreadyExists(username)
        user = {"id": len(users) + 1, "username": username, "password_hash": password_hash, "threads": []}
        users[username] = user
        return user

    def find_user(username):
        return next((user for name, user in users.items() if name.lower() == username.lower()), None)

    def owns(user_id, thread_id):
        return any(user["id"] == user_id and thread_id in user["threads"] for user in users.values())

    def add_thread(user_id, thread_id, title):
        for user in users.values():
            if user["id"] == user_id:
                user["threads"].append(thread_id)
                titles[thread_id] = title
                return True
        return False

    def list_conversations(user_id):
        user = next((item for item in users.values() if item["id"] == user_id), None)
        if user is None:
            return None
        return [{"thread_id": thread_id, "title": titles.get(thread_id)} for thread_id in user["threads"]]

    def remove_thread(user_id, thread_id):
        for user in users.values():
            if user["id"] == user_id and thread_id in user["threads"]:
                user["threads"].remove(thread_id)
                titles.pop(thread_id, None)
                return True
        return False

    monkeypatch.setattr("app.auth_router.create_user", create_user)
    monkeypatch.setattr("app.auth_router.find_login_user", find_user)
    monkeypatch.setattr("app.chat_router.list_user_conversations", list_conversations)
    monkeypatch.setattr("app.chat_router.user_owns_thread", owns)
    monkeypatch.setattr("app.chat_router.remove_user_thread", remove_thread)
    monkeypatch.setattr("app.ai_router.user_owns_thread", owns)
    monkeypatch.setattr("app.ai_router.add_user_thread", add_thread)

    app = FastAPI()
    app.state.agent_graph = FakeGraph()
    app.include_router(auth_router)
    app.include_router(chat_router)
    app.include_router(ai_flight_router)

    async def no_database_pool():
        yield

    app.dependency_overrides[database_pool_for_route] = no_database_pool

    with TestClient(app) as client:
        # 未登录时，页面跳转登录；API 返回 401。
        assert client.get("/chats", follow_redirects=False).headers["location"] == "/login"
        assert client.post("/ai_flight/model", json={"question": "你好"}).status_code == 401
        assert client.post("/auth/register", data={"username": "Bob", "password": "123456"}).status_code == 409
        assert "用户名已存在" in client.post("/auth/register", data={"username": "Bob", "password": "123456"}).text
        assert "用户名已存在" in client.post("/auth/register", data={"username": "bOb", "password": "123456"}).text
        assert client.post("/auth/register", data={"username": "Carol", "password": "secret"}, follow_redirects=False).headers["location"] == "/login?registered=1"
        assert client.post("/auth/login", data={"username": "nobody", "password": "bad"}).status_code == 401
        assert "用户名输入错误或用户名不存在" in client.post("/auth/login", data={"username": "nobody", "password": "bad"}).text
        assert "密码输入错误" in client.post("/auth/login", data={"username": "Bob", "password": "bad"}).text
        assert "密码输入错误" in client.post("/auth/login", data={"username": "bOb", "password": "bad"}).text

        login = client.post("/auth/login", data={"username": "bOb", "password": "123456"}, follow_redirects=False)
        # 首轮创建的 ID 归 Bob，下一轮继续使用同一个检查点。
        assert login.status_code == 303 and login.headers["location"] == "/chats"
        assert "httponly" in login.headers["set-cookie"].lower()
        assert read_access_token(client.cookies.get(COOKIE_NAME)).user_name == "Bob"
        assert "新建 AI 对话" in client.get("/chats").text
        # 已有会话没有标题，继续显示原编号。
        assert f"会话 {str(legacy_thread_id)[:9]}" in client.get("/chats").text
        assert client.get("/chat/new").status_code == 200
        assert client.post("/chat/new/messages", data={"question": "   "}).status_code == 422
        started = client.post("/chat/new/messages", data={"question": "第一问"}, follow_redirects=False)
        assert started.status_code == 303
        thread_id = UUID(started.headers["location"].split("=")[1])
        assert thread_id in users["Bob"]["threads"]
        # 新会话以第一条提问命名；链接仍使用完整 UUID 定位。
        listing = client.get("/chats").text
        assert f"/chat?thread_id={thread_id}" in listing
        assert "第一问" in listing
        assert f"<small>{thread_id}</small>" not in listing
        assert "回答：第一问" in client.get(started.headers["location"]).text
        continued = client.post(f"/chat/messages?thread_id={thread_id}", data={"question": "第二问"}, follow_redirects=False)
        assert continued.status_code == 303
        assert "回答：第二问" in client.get(continued.headers["location"]).text
        assert titles[thread_id] == "第一问"

        # 经 API 创建会话也应保存首条提问，而不是仅给网页入口命名。
        api_started = client.post("/ai_flight/model", json={"question": "API首问"})
        assert api_started.status_code == 200
        api_thread_id = UUID(api_started.json()["thread_id"])
        assert titles[api_thread_id] == "API首问"

        # 打开确认页或选择取消都不删除；提交时必须带这条会话专属的短期确认令牌。
        confirmation = client.get(f"/chats/{thread_id}/delete")
        assert confirmation.status_code == 200
        assert "第一问" in confirmation.text and "确认删除" in confirmation.text
        token = re.search(r'name="confirmation_token" value="([^"]+)"', confirmation.text).group(1)
        assert client.get("/chats").status_code == 200
        assert thread_id in users["Bob"]["threads"]
        assert client.post(f"/chats/{thread_id}/delete", data={"confirmation_token": "bad"}).status_code == 403
        assert thread_id in users["Bob"]["threads"]

        # 换成 Alice 后，即使知道 Bob 的 UUID，页面和旧 API 都不能读取或续聊。
        client.post("/auth/login", data={"username": "Alice", "password": "123456"}, follow_redirects=False)
        assert client.get(f"/chats/{thread_id}/delete").status_code == 404
        assert client.post(f"/chats/{thread_id}/delete", data={"confirmation_token": token}).status_code == 403
        forged_for_alice = issue_delete_confirmation(AuthIdentity(2, "Alice"), thread_id)
        assert client.post(f"/chats/{thread_id}/delete", data={"confirmation_token": forged_for_alice}).status_code == 404
        assert thread_id in users["Bob"]["threads"]
        assert client.get(f"/chat?thread_id={thread_id}").status_code == 404
        assert client.post("/ai_flight/model", json={"question": "偷看", "thread_id": str(thread_id)}).status_code == 404
        assert client.post("/ai_flight/assistant/model", json={"question": "偷看", "thread_id": str(thread_id)}).status_code == 404
        assert client.post(f"/chat/messages?thread_id={thread_id}", data={"question": "偷看"}).status_code == 404
        assert client.post("/ai_flight/model", json={"question": "新问题", "thread_id": str(uuid4())}).status_code == 404

        # Bob 确认后仅移除这一条会话；另一条和旧会话仍保留。
        client.post("/auth/login", data={"username": "Bob", "password": "123456"}, follow_redirects=False)
        deleted = client.post(f"/chats/{thread_id}/delete", data={"confirmation_token": token}, follow_redirects=False)
        assert deleted.status_code == 303 and deleted.headers["location"] == "/chats"
        assert thread_id not in users["Bob"]["threads"] and thread_id not in titles
        assert legacy_thread_id in users["Bob"]["threads"]
        assert api_thread_id in users["Bob"]["threads"]
        assert f"/chat?thread_id={thread_id}" not in client.get("/chats").text
        assert client.get(f"/chat?thread_id={thread_id}").status_code == 404
        assert client.post("/ai_flight/model", json={"question": "继续", "thread_id": str(thread_id)}).status_code == 404
        assert client.post(f"/chats/{thread_id}/delete", data={"confirmation_token": token}).status_code == 404
        assert str(thread_id) in app.state.agent_graph.states
