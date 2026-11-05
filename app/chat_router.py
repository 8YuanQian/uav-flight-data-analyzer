# 用户查看和继续 Agent graph 对话的浏览器页面。

from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from src.auth.security import AuthIdentity, InvalidAccessToken, issue_delete_confirmation, verify_delete_confirmation
from src.database.user_repository import list_user_conversations, remove_user_thread, user_owns_thread
from src.schemas import UserQuestion

from .ai_router import invoke_user_agent_graph
from .auth_dependencies import identity_from_request, require_user
from .database_dependency import database_pool_for_route


chat_router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# 页面遇到无效登录时返回 None，由对应路由跳转登录页。
def _browser_user(request: Request):
    try:
        return identity_from_request(request)
    except InvalidAccessToken:
        return None


# 读取检查点，提取适合页面展示的用户与助手消息。
def _chat_messages(request: Request, thread_id: UUID) -> list[dict]:
    config = {"configurable": {"thread_id": str(thread_id)}}
    # Agent graph 的检查点由 PostgreSQL 保存；这里不重新执行 graph。
    state = request.app.state.agent_graph.get_state(config).values
    if not state:
        raise HTTPException(status_code=404, detail="对话不存在")
    messages = []
    for item in state.get("message", []):
        # 工具调用和工具结果也可能在状态中，但聊天页只显示双方发言。
        if item.get("role") not in ("user", "assistant"):
            continue
        content = item.get("content", "")
        if isinstance(content, dict):
            # Agent 最终回复是结构化对象，页面只展示其中的 answer 文本。
            content = content.get("answer", "")
        messages.append({"role": item["role"], "content": str(content)})
    return messages


@chat_router.get("/chats", dependencies=[Depends(database_pool_for_route)], include_in_schema=False)
def conversation_list(request: Request):
    user = _browser_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    # user_id 来自已验证的 JWT，而不是浏览器传入的任意用户编号。
    conversations = list_user_conversations(user.user_id)
    if conversations is None:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "chats.html", {"user": user, "conversations": conversations})


@chat_router.get("/chats/{thread_id}/delete", dependencies=[Depends(database_pool_for_route)], include_in_schema=False)
def confirm_delete_chat(request: Request, thread_id: UUID):
    user = _browser_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    # 只为当前用户拥有的这一条会话显示确认页面。
    conversations = list_user_conversations(user.user_id) or []
    conversation = next((item for item in conversations if item["thread_id"] == thread_id), None)
    if conversation is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    return templates.TemplateResponse(request, "delete_chat.html", {
        "conversation": conversation,
        "confirmation_token": issue_delete_confirmation(user, thread_id),
    })


@chat_router.post("/chats/{thread_id}/delete", dependencies=[Depends(database_pool_for_route)], status_code=303)
def delete_chat(
    thread_id: UUID,
    confirmation_token: str = Form(),
    user: AuthIdentity = Depends(require_user),
):
    # 先核对确认令牌；它必须属于当前已登录用户和 URL 指向的单个会话。
    if not verify_delete_confirmation(confirmation_token, user, thread_id):
        raise HTTPException(status_code=403, detail="删除确认已失效，请重新确认")
    # 仓储层再用原子 UPDATE 核对归属；不能仅凭确认令牌或 thread_id 删除。
    if not remove_user_thread(user.user_id, thread_id):
        raise HTTPException(status_code=404, detail="对话不存在")
    return RedirectResponse("/chats", status_code=303)


@chat_router.get("/chat/new", include_in_schema=False)
def new_chat_page(request: Request):
    user = _browser_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "chat.html", {"user": user, "thread_id": None, "messages": []})


@chat_router.post("/chat/new/messages", dependencies=[Depends(database_pool_for_route)], include_in_schema=False)
def start_chat(request: Request, question: str = Form()):
    user = _browser_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    question = question.strip()
    if not question:
        return templates.TemplateResponse(request, "chat.html", {"user": user, "thread_id": None, "messages": [], "error": "请输入问题"}, status_code=422)
    # 首次提问不传 thread_id：graph 生成新检查点后才将 ID 归到该用户。
    result = invoke_user_agent_graph(UserQuestion(question=question), request, user)
    return RedirectResponse(f"/chat?thread_id={result['thread_id']}", status_code=303)


@chat_router.get("/chat", dependencies=[Depends(database_pool_for_route)], include_in_schema=False)
def chat_page(request: Request, thread_id: UUID):
    user = _browser_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    # URL 中的 UUID 只用于定位；读取历史记录前仍须确认会话归属。
    if not user_owns_thread(user.user_id, thread_id):
        raise HTTPException(status_code=404, detail="对话不存在")
    return templates.TemplateResponse(request, "chat.html", {
        "user": user, "thread_id": thread_id,
        "messages": _chat_messages(request, thread_id),
    })


@chat_router.post("/chat/messages", dependencies=[Depends(database_pool_for_route)], include_in_schema=False)
def continue_chat(request: Request, thread_id: UUID, question: str = Form()):
    user = _browser_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    # 写入下一轮消息前也做归属检查，防止直接构造 POST 请求越权提问。
    if not user_owns_thread(user.user_id, thread_id):
        raise HTTPException(status_code=404, detail="对话不存在")
    question = question.strip()
    if not question:
        return templates.TemplateResponse(request, "chat.html", {
            "user": user, "thread_id": thread_id,
            "messages": _chat_messages(request, thread_id), "error": "请输入问题",
        }, status_code=422)
    invoke_user_agent_graph(UserQuestion(question=question, thread_id=thread_id), request, user)
    return RedirectResponse(f"/chat?thread_id={thread_id}", status_code=303)
