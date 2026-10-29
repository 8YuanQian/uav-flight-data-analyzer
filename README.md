# 无人机飞行数据分析项目

这个项目包含四个部分：

- 读取飞行 CSV，清洗数据、计算统计信息，并调用模型生成分析报告。
- 将分析记录保存在 PostgreSQL 中，通过接口或自然语言问题查询记录。
- 从无人机知识资料中检索相关内容，重新排序后回答问题，并比较检索效果。
- 通过 LangGraph Agent 组合飞行查询、分析和知识检索。

## 文件放在哪里

```text
UAV_project/
├── api.py, main.py
├── src/              # flight_data, plot, database, rag, llm, agent
├── examples/, scripts/, tests/
├── data/, reference/, sql/, backups/
└── requirements.txt, requirements-dev.txt
```

在线问答接口通过 `app/ai_router.py` 调用 `src/agent/graph/graph.py` 中的 Agent graph，由 graph 按问题选择飞行数据或 RAG 工具并生成回答。`src/agent/flight_qa.py` 是保留的旧实现，当前接口不再调用。

## 准备 Python 环境

使用 Python 3.11，在项目根目录打开 PowerShell。已有 `.venv` 时保留它；没有时再创建：

```powershell
if (-not (Test-Path .venv)) {
    uv venv --python 3.11 .venv
}
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
```

依赖版本主要来自整理时项目环境中已安装的版本，并补上启动接口、接收上传文件所需的包。这是直接依赖清单；安装命令仍需要在你的环境中执行。下面的运行命令直接使用项目解释器，不需要先激活环境。

## 设置环境变量

代码通过 `os.getenv()` 读取配置。请在运行程序的同一个 PowerShell 窗口设置变量：

```powershell
$env:DEEPSEEK_API_KEY = "填入你的模型 API 密钥"
$env:PASSWORD = "填入你的 PostgreSQL 密码"
$env:UAV_DB_NAME = "uav_project"
$env:PORT = "5432"
```

| 变量 | 用途 | 当前默认值 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | 模型服务密钥；接口启动时也会检查它 | 无 |
| `PASSWORD` | PostgreSQL 密码 | 无 |
| `UAV_DB_NAME` | 数据库名称 | `uav_project` |
| `PORT` | PostgreSQL 端口 | `5432` |

数据库主机和用户目前在 `src/database/connection.py` 中固定为 `localhost`、`postgres`。项目没有自动加载 `.env` 的代码，因此只创建 `.env` 文件不会使配置生效。密钥和密码不要写进代码或提交到仓库。

## 准备数据库

新的飞行业务使用 `uavs` 和一张空的新版 `flight_records` 表。`sql/create_uavs_and_new_flight_records.sql` 是一次性切换脚本：把原 `flight_records` 改名为 `flight_records_legacy`，再建两张空表；原 `flight_analyses` 和旧飞行记录均不迁移、不删除。切换数据库结构前，先停止仍运行旧代码的 API 和 worker；部署新代码后再启动它们。不要重复执行该脚本。

知识检索还需要 pgvector 扩展，以及 `documents` 表中的 `content`、`source`、`metadata`、`embedding` 字段。`metadata` 保存 JSON 对象，`embedding` 保存向量，其维度需要与所用模型的输出一致。当前 `sql/PostgreSQL.sql` 尚未提供这张表的建表语句，运行资料导入和检索前需要准备好这张表。

## 启动接口

```powershell
.\.venv\Scripts\python.exe -m uvicorn api:app --reload
```

启动后打开 [接口文档](http://127.0.0.1:8000/docs)。主要接口如下：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/health` | 检查服务状态 |
| POST | `/flight/uavs` | 单独登记飞行器；重复 `uav_code` 返回 409 |
| POST | `/flight/flights/validate` | 校验一条 CSV 时间区间 |
| POST | `/ai_flight/flights/report` | 上传 CSV 并提交 Celery 任务；立即返回任务 ID |
| GET | `/ai_flight/report/jobs/{task_id}` | 查询任务状态及完成后的处理结果 |
| GET | `/flight/flights/{record_id}` | 按数据库生成的 ID 查询飞行记录 |
| GET | `/flight/flights?limit=5&uav_code=UAV-1` | 查询最近记录，可按飞行器编号筛选 |
| POST | `/ai_flight/flights/{record_id}/report/jobs` | 将某条记录的报表生成提交给 Celery |

上传接口只把文件暂存到 API 与 worker 共用的 `CSV_UPLOAD_DIR`，然后投递 `uav.process_flights_csv` 任务，返回 HTTP 202 和 `task_id`；它不申请 API 数据库连接。worker 读取暂存文件后完成解析、校验、计算、入库、清除列表缓存和逐组生成 AI 报告，并在任务结束时删除暂存文件。通过 `GET /ai_flight/report/jobs/{task_id}` 查询 `PENDING`、`SUCCESS` 或 `FAILURE`；成功时 `result` 是原先上传接口返回的完整分析结果。CSV 无效时返回 `INVALID_CSV` 和原因；入库成功但缓存清除失败时返回 `CACHE_UPDATE_FAILED` 和已保存的记录 ID；入库后模型失败时返回 `REPORT_FAILED` 和已保存的记录 ID。其他错误也会使任务失败。

上传 CSV 需要 `uav_code,uav_model,manufacturer,flight_id,start_time,end_time,height,speed,battery,temperature`。每行是一段时间区间；同一 `uav_code` 和 `flight_id` 的行属于同一次飞行。时间必须写为 `YYYY-MM-DD HH:mm`，按北京时间解释，结束时间必须晚于开始时间，同组区间不能重叠。运行分钟数取该组最早开始到最晚结束的跨度，包含区间之间的空档。`flight_id` 仅用于本次分组，不写入数据库；新表的 `id` 由数据库生成。重复上传会生成新的飞行记录。每组独立填值、插值，整份 CSV 的所有记录在同一事务中写入。示例：

```csv
uav_code,uav_model,manufacturer,flight_id,start_time,end_time,height,speed,battery,temperature
UAV-1,M1,Maker,flight-a,2026-10-28 10:00,2026-10-28 10:05,10,2,90,20
UAV-1,M1,Maker,flight-a,2026-10-28 10:10,2026-10-28 10:20,12,3,80,21
```

已有 `uav_code` 在导入时会被复用，不更新其型号或制造商；单独登记已有编号则报“飞行器 ID 重复”。仓库现有的 `data/data.csv` 仍是旧格式，缺少飞行器编号和起止时间，不能直接上传到这个新版接口。

Docker Compose 已为 API 和 worker 挂载同一个 `csv_uploads` 卷，二者必须使用相同的 `CSV_UPLOAD_DIR`。如果一个进程在宿主机、另一个在容器里运行，需要另外配置双方可见的共享目录；仅使用各自的默认临时目录无法传递文件。worker 异常退出或投递状态不明时可能留下暂存文件，需按文件标识检查并清理。Compose 中的 API 使用已挂载的 Hugging Face 模型缓存离线启动，首次运行前要保证所需模型已经缓存。

问答接口的请求体示例：

```json
{"question": "最近一次飞行的最高速度是多少？"}
```

`POST /ai_flight/model` 和 `POST /ai_flight/assistant/model` 首次调用不传 `thread_id`，响应会返回一个新的 `thread_id`。下一轮把它原样传回去，例如：

```json
{"question": "那它的最低电量呢？", "thread_id": "上一轮响应中的 thread_id"}
```

Agent 的对话状态由 LangGraph `PostgresSaver` 保存在 PostgreSQL；同一个 `thread_id` 会恢复历史消息和摘要，未知编号返回 404。FastAPI 启动时会运行一次检查点表初始化，并在关闭时释放专用连接池。检查点池最多使用 2 条连接，原有 API 业务池上限仍为 5 条；数据库需要为同一 API 进程预留最多 7 条连接。命令行 `main.py` 演示仍使用内存检查点。

## 运行知识问答、Agent 演示和检索评估

先准备知识数据库，按需要运行以下命令：

```powershell
# 导入 data/uav_knowledge.json，会向数据库写入资料
.\.venv\Scripts\python.exe -m examples.import_documents

# 运行知识问答演示
.\.venv\Scripts\python.exe -m examples.rag_demo

# 运行 LangGraph Agent 演示
.\.venv\Scripts\python.exe main.py
```

重复运行资料导入会重复插入资料。检索使用 `intfloat/multilingual-e5-base`，重新排序使用 `BAAI/bge-reranker-base`；首次使用时可能需要下载模型。其他独立演示的用途和运行方式见 [examples/README.md](examples/README.md)。

评估用例来自 `data/rag_test_cases.json`。评估函数位于 `src/rag/evaluation.py`；调用时需传入 `embedding_model`，重排评估还需传入 `rerank_model`。两种评估共用 `calculate_metrics()`，保留原来的计算含义：

- `mean_recall`：至少命中一次期望主题的问题占比。这里沿用原项目的名称，计算的是主题命中率。
- `mean_precision`：每个问题中，期望主题的资料占检索结果的比例，再对全部问题取平均。
- `mean_mrr`：第一条命中资料的排名倒数，再对全部问题取平均。

没有检索结果时，该问题的三个指标均为 0。评估用例为空时显示提示，三个指标均显示为 0。检索距离筛选和重新排序规则保持原有设置。

## 更新飞行记录（乐观锁）

读取 `GET /flight/flights/{record_id}` 后，把返回的 `version` 和完整汇总字段提交给 `PUT /flight/flights/{record_id}`。接口根据带时区的 `start_time`、`end_time` 重新计算 `duration_minutes`，无需提交时长：

```json
{
  "version": 1,
  "filename": "revised.csv",
  "start_time": "2026-10-28T10:00:00+08:00",
  "end_time": "2026-10-28T10:20:00+08:00",
  "row_count": 10,
  "average_height": 50.0,
  "average_speed": 12.0,
  "average_temperature": 26.0,
  "max_height": 70.0,
  "max_speed": 18.0,
  "max_temperature": 30.0,
  "minimum_battery": 40.0,
  "battery_start": 90.0,
  "battery_end": 80.0,
  "anomaly_status": "normal",
  "anomaly_reason": null
}
```

更新成功返回完整记录和递增后的 `version`。版本过期返回 HTTP 409，记录不存在返回 HTTP 404；收到 409 时先重新读取，再决定如何处理最新数据。更新成功后会清除该记录和列表的 Redis 缓存；数据库已提交但缓存清除失败时返回 HTTP 503，同时附上记录 ID 和新版本。此时读取接口可能暂时返回旧缓存，不要拿旧版本反复重试。

## 运行已有测试

测试依赖单独安装在项目环境中：

```powershell
uv pip install --python .venv\Scripts\python.exe -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest verification -q
```

现有 `tests/conftest.py` 会指定 `uav_project_test` 数据库，并在每个测试前后清空其中的 `flight_analyses` 表；旧测试尚未全部迁移到新表，暂不作为新版流程的验证依据。`verification` 是隔离的新流程测试，不访问数据库或模型。

当前测试中还有一个未完成的工具测试；测试组织也会让不查询数据库的用例依赖数据库。这次整理保留了这些测试文件，所以以上命令不代表全部测试已经通过。


## 新结构

Agent 的 rag_search 工具位于 src/agent/tools/rag_search.py；summary 节点位于 src/agent/graph/nodes/summary_node.py。当前项目已同步新结构；运行前需配置数据库与模型服务。
