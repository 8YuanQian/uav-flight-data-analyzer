from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from langgraph.types import Overwrite
from kombu.exceptions import OperationalError

from src.flight_data.load_data import load_json_data
from src.rag.document_save_to_database import save_document_to_database
from src.schemas import AssistantResponse, UserQuestion
from .csv_upload import CsvCacheError, CsvReportError, CsvValidationError, stage_csv_upload
from .database_dependency import database_pool_for_route

ai_flight_router = APIRouter(prefix="/ai_flight")


def _invoke_agent_graph(question: UserQuestion, request: Request) -> dict:
    """新请求创建会话；带 thread_id 的请求从 PostgreSQL 恢复会话。"""
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


@ai_flight_router.post("/flights/{record_id}/report/jobs", status_code=202)
def submit_flight_report_job(record_id: int, request: Request):
    # 只负责提交任务；记录是否存在由 Celery worker 查询并校验。
    try:
        task = request.app.state.celery_app.send_task(
            "uav.generate_flight_report", args=[record_id], retry=False
        )
    except OperationalError:
        raise HTTPException(status_code=503, detail="Task queue unavailable")
    return {"task_id": task.id, "status": "PENDING"}


@ai_flight_router.get("/report/jobs/{task_id}")
def get_flight_report_job(task_id: str, request: Request):
    task = request.app.state.celery_app.AsyncResult(task_id)
    response = {"task_id": task_id, "status": task.status}
    if task.successful():
        response["result"] = task.result
    elif task.failed():
        if isinstance(task.result, CsvValidationError):
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
                "message": "飞行记录已保存，但 AI 报告生成失败",
                "record_ids": task.result.record_ids,
            }
        else:
            response["error"] = "REPORT_FAILED"
    return response



@ai_flight_router.post("/model", dependencies=[Depends(database_pool_for_route)])
def answer_flight_question_to_user(question: UserQuestion, request: Request):
    answer = _invoke_agent_graph(question, request)
    return {"answer": answer["answer"], "thread_id": answer["thread_id"]}


@ai_flight_router.post("/assistant/model",response_model=AssistantResponse,dependencies=[Depends(database_pool_for_route)],)
def use_flight_assistant_answer_query(question: UserQuestion, request: Request):
    return _invoke_agent_graph(question, request)


@ai_flight_router.post("/flights/report", status_code=202)
def analyze_flights_csv(file: UploadFile, request: Request):
    """Stage the upload and publish a task; processing happens in the worker."""
    try:
        upload_id = stage_csv_upload(file.file)
    except OSError as exc:
        raise HTTPException(status_code=503, detail="暂存上传文件失败，请稍后重试") from exc
    try:
        task = request.app.state.celery_app.send_task(
            "uav.process_flights_csv",
            args=[upload_id, file.filename, file.content_type],
            retry=False,
        )
    except OperationalError as exc:
        # 投递失败也可能是响应丢失；保留文件，防止已入队的任务找不到输入。
        raise HTTPException(status_code=503, detail="Task queue unavailable") from exc
    return {"task_id": task.id, "status": "PENDING"}
