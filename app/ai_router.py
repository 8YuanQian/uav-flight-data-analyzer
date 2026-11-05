from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from langgraph.types import Overwrite
from kombu.exceptions import OperationalError

from src.flight_data.load_data import load_json_data
from src.rag.document_save_to_database import save_document_to_database
from src.schemas import AssistantResponse, UserQuestion
from src.auth.security import AuthIdentity
from src.auth.data_scope import use_data_user
from src.database.flight_record_repository import get_flight_by_id, user_owns_flight_records
from src.database.uav_repository import UavOwnershipConflict
from src.database.user_repository import add_user_thread, user_owns_thread
from src.database.csv_upload_repository import UploadUserNotFound, release_csv_upload, reserve_csv_upload
from src.database.flight_report_job_repository import (
    ReportUserNotFound, release_flight_report_job, reserve_flight_report_job,
    get_report_record_id,
)
from src.database.task_lease_repository import get_task_owner, get_task_state, register_task
from .auth_dependencies import require_user, user_data_scope
from .csv_upload import CsvCacheError, CsvReportError, CsvValidationError, stage_csv_upload, staged_csv_path
from .database_dependency import database_pool_for_route

ai_flight_router = APIRouter(prefix="/ai_flight")


# 新请求创建会话；带 thread_id 的请求从 PostgreSQL 恢复会话。
def _invoke_agent_graph(question: UserQuestion, request: Request) -> dict:
    thread_id = str(question.thread_id or uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    graph = request.app.state.agent_graph
    if question.thread_id is not None and not graph.get_state(config).values:
        raise HTTPException(status_code=404, detail="对话不存在，请不传 thread_id 创建新对话")

    query = question.question
    initial_state = {
        "query": query,
        # 这两个字段使用列表累加器；每轮开始时显式清空上一轮的临时结果。
        "context": Overwrite([]),
        "message": [{"role": "user", "content": query}],
        "current_tool_call": None,
        "tool_results": Overwrite([]),
        "answer": "",
        "finished": False,
    }
    if question.thread_id is None:
        initial_state["conversation_summary"] = ""
        initial_state["summary_cursor"] = 0
    result = graph.invoke(initial_state, config=config)
    return {**result["answer"], "thread_id": thread_id}


# 仅允许会话所有者续聊；首次回答完成后才登记新会话。
def invoke_user_agent_graph(question: UserQuestion, request: Request, user: AuthIdentity) -> dict:
    # 续聊必须先查归属，再读取该 ID 对应的 graph 检查点。
    if question.thread_id is not None and not user_owns_thread(user.user_id, question.thread_id):
        raise HTTPException(status_code=404, detail="对话不存在")
    if question.thread_id is None and not question.question.strip():
        raise HTTPException(status_code=422, detail="请输入问题")
    with use_data_user(user.user_id):
        answer = _invoke_agent_graph(question, request)
    # 首轮执行成功后，在同一事务中登记归属和标题；旧会话不补写标题。
    if question.thread_id is None and not add_user_thread(
        user.user_id, UUID(answer["thread_id"]), question.question.strip()
    ):
        raise HTTPException(status_code=401, detail="用户不存在，请重新登录")
    return answer


@ai_flight_router.post("/flights/{record_id}/report/jobs", status_code=202,
                       dependencies=[Depends(database_pool_for_route)])
def submit_flight_report_job(
    record_id: int,
    request: Request,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    user: AuthIdentity = Depends(user_data_scope),
):
    # 同一用户的同一个键只创建一次任务；飞行记录是否存在仍由 worker 校验。
    task_id = uuid4()
    try:
        existing = reserve_flight_report_job(user.user_id, idempotency_key, record_id, task_id)
    except ReportUserNotFound as exc:
        raise HTTPException(status_code=401, detail="用户不存在，请重新登录") from exc
    if existing is not None:
        original_task_id, original_record_id = existing
        message = ("重复请求：该幂等键已使用" if original_record_id == record_id
                   else "该幂等键已用于另一条飞行记录")
        raise HTTPException(status_code=409, detail={
            "message": message, "task_id": str(original_task_id),
        })
    try:
        register_task(task_id, user.user_id)
    except Exception:
        release_flight_report_job(user.user_id, idempotency_key, task_id)
        raise
    try:
        task = request.app.state.celery_app.send_task(
            "uav.generate_flight_report", args=[record_id], task_id=str(task_id), retry=False
        )
    except OperationalError as exc:
        raise HTTPException(status_code=503, detail={
            "message": "任务提交状态不确定，请用任务 ID 查询，勿换新幂等键重试",
            "task_id": str(task_id),
        }) from exc
    return {"task_id": task.id, "status": "PENDING"}


@ai_flight_router.get("/report/jobs/{task_id}", dependencies=[Depends(database_pool_for_route)])
def get_flight_report_job(
    task_id: str, request: Request, user: AuthIdentity = Depends(user_data_scope)
):
    try:
        task_uuid = UUID(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    # 先核对归属，再访问任务状态或 Redis 结果；他人的任务统一返回 404。
    if get_task_owner(task_uuid) != user.user_id:
        raise HTTPException(status_code=404, detail="任务不存在")
    state = get_task_state(task_uuid)
    task = request.app.state.celery_app.AsyncResult(task_id)
    response = {"task_id": task_id, "status": state["status"] if state else task.status}
    if state and state["status"] == "SUCCESS":
        _authorize_report_result(task_uuid, state["result"])
        response["result"] = state["result"]
        return response
    if state and state["status"] in {"PENDING", "RUNNING", "COMMITTED", "RETRY"}:
        return response
    if state and state["status"] == "FAILED" and not task.failed():
        response["error"] = "REPORT_FAILED"
        return response
    if task.successful():
        _authorize_report_result(task_uuid, task.result)
        response["result"] = task.result
    elif task.failed():
        if isinstance(task.result, (CsvValidationError, UavOwnershipConflict)):
            response["error"] = "INVALID_CSV"
            response["detail"] = str(task.result)
        elif isinstance(task.result, CsvCacheError):
            response["error"] = "CACHE_UPDATE_FAILED"
            response["detail"] = {
                "message": "飞行记录已保存，但缓存更新失败",
                "record_ids": task.result.record_ids,
            }
        elif isinstance(task.result, CsvReportError):
            response["error"] = "REPORT_FAILED"
            response["detail"] = {
                "message": "AI 报告生成失败，本次上传的飞行记录未入库",
                "uav_code": task.result.uav_code,
                "csv_flight_id": task.result.csv_flight_id,
            }
        else:
            response["error"] = "REPORT_FAILED"
    return response


def _authorize_report_result(task_id, result):
    # 历史任务结果也要按现行数据归属核验，不能用旧报表绕过飞行记录权限。
    if isinstance(result, dict) and isinstance(result.get("flights"), list):
        if user_owns_flight_records([flight.get("id") for flight in result["flights"]]):
            return
    else:
        record_id = get_report_record_id(task_id)
        if record_id is not None and get_flight_by_id(record_id) is not None:
            return
    raise HTTPException(status_code=404, detail="报告对应的飞行记录不存在")


@ai_flight_router.post("/model", dependencies=[Depends(database_pool_for_route)])
def answer_flight_question_to_user(question: UserQuestion, request: Request, user: AuthIdentity = Depends(user_data_scope)):
    # 旧问答入口同样使用登录依赖和会话归属校验，不能绕过聊天页面。
    answer = invoke_user_agent_graph(question, request, user)
    return {"answer": answer["answer"], "thread_id": answer["thread_id"]}


@ai_flight_router.post("/assistant/model",response_model=AssistantResponse,dependencies=[Depends(database_pool_for_route)],)
def use_flight_assistant_answer_query(question: UserQuestion, request: Request, user: AuthIdentity = Depends(user_data_scope)):
    return invoke_user_agent_graph(question, request, user)


# 上传接口只暂存文件并投递任务，具体处理由 Celery worker 执行。
@ai_flight_router.post("/flights/report", status_code=202, dependencies=[Depends(database_pool_for_route)])
def analyze_flights_csv(
    file: UploadFile,
    request: Request,
    idempotency_key: UUID = Form(),
    user: AuthIdentity = Depends(user_data_scope),
):
    # 先用数据库唯一约束占用当前用户的键，再暂存文件和投递任务。
    task_id = uuid4()
    try:
        existing_task_id = reserve_csv_upload(user.user_id, idempotency_key, task_id)
    except UploadUserNotFound as exc:
        raise HTTPException(status_code=401, detail="用户不存在，请重新登录") from exc
    if existing_task_id is not None:
        # 重复提交仍返回 409，但响应体与首次提交使用相同的两个字段。
        state = get_task_state(existing_task_id)
        status = (state["status"] if state is not None
                  else request.app.state.celery_app.AsyncResult(str(existing_task_id)).status)
        return JSONResponse(
            status_code=409,
            content={"task_id": str(existing_task_id), "status": status},
        )

    try:
        upload_id = stage_csv_upload(file.file)
    except OSError as exc:
        # 文件尚未进入队列，可以安全地释放键，允许用户用原键重试。
        release_csv_upload(user.user_id, idempotency_key, task_id)
        raise HTTPException(status_code=503, detail="暂存上传文件失败，请稍后重试") from exc
    try:
        # 先提交任务状态，worker 收到消息后才能原子认领。
        register_task(task_id, user.user_id)
    except Exception:
        staged_csv_path(upload_id).unlink(missing_ok=True)
        release_csv_upload(user.user_id, idempotency_key, task_id)
        raise
    try:
        task = request.app.state.celery_app.send_task(
            "uav.process_flights_csv",
            args=[upload_id, file.filename, file.content_type],
            task_id=str(task_id),
            retry=False,
        )
    except OperationalError as exc:
        # 投递响应丢失时任务可能已进入队列；保留键和文件，避免重试产生第二个任务。
        raise HTTPException(
            status_code=503,
            detail={"message": "任务提交状态不确定，请用任务 ID 查询，勿换新幂等键重试", "task_id": str(task_id)},
        ) from exc
    return {"task_id": task.id, "status": "PENDING"}
