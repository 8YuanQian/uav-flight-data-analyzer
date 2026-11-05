# 无人机飞行数据分析项目

这个项目包含四个部分：

- 读取飞行 CSV，清洗数据、计算统计信息，并调用模型生成分析报告。
- 将分析记录保存在 PostgreSQL 中，通过接口或自然语言问题查询记录。
- 从无人机知识资料中检索相关内容，重新排序后回答问题，并比较检索效果。
- 通过 LangGraph Agent 组合飞行查询、分析和知识检索。

## 文件放在哪里

```text
UAV_project_refactored/
├── api.py, main.py
├── app/              # FastAPI、路由、Celery 任务及页面模板
├── src/              # flight_data, plot, database, rag, llm, agent
├── compose*.yaml, Dockerfile
├── examples/, scripts/, tests/, verification/
├── archive/learning/  # 历史实现及原始快照，不参与业务运行
├── data/, reference/, sql/, backups/, logs/, docs/
├── .env.example, .env.test.example
└── requirements.txt, requirements-dev.txt
```

在线问答接口通过 `app/ai_router.py` 调用 `src/agent/graph/graph.py` 中的 Agent graph，由 graph 按问题选择飞行数据或 RAG 工具并生成回答。旧循环 Agent、旧问答和旧表实现已移入 `archive/learning/`。当前目录职责和调用关系见 [项目结构说明](docs/project_structure.md)，归档路径与校验清单见 [历史学习版本](archive/learning/README.md)。

## Docker 部署

Compose 项目 `uav-project` 统一管理 PostgreSQL、Redis、正式 API/worker 和可选的测试 API/worker。`db-init` 负责建库和结构迁移，`model-init` 负责准备模型及分词器缓存；二者成功退出后才启动 API 和 worker，`Exited (0)` 是正常状态。

本机已于 2026-11-04 完成迁移，迁移后停用的 6 个旧容器已删除，旧数据卷和迁移备份保留。当前复用 E 盘模型缓存，更新本机正式和测试容器时执行：

```powershell
docker compose -f compose.yaml -f compose.test.yaml -f compose.local.yaml -f compose.test.local.yaml up -d --build api worker api-test worker-test
```

新机器使用默认命名卷和自建网络，不要求外部数据库容器、预建网络或固定 E 盘路径。先按下文填写 `.env`；需要测试环境时另行准备 `.env.test`，再执行：

```powershell
docker compose up -d --build api worker
# .env.test 填好独立 JWT 密钥后启动测试服务
docker compose -f compose.yaml -f compose.test.yaml up -d --build api-test worker-test
```

正式入口默认 8002，测试入口默认 8003。`compose.test.yaml` 是补充配置，不能单独启动；`compose.existing.yaml`、`compose.existing-test.yaml` 只保留为旧部署记录，不再用于日常启动。首次构建和模型准备需要网络。完整维护命令见 [部署说明](docs/deployment.md)，本次迁移核验见 [迁移报告](docs/compose_migration_20261104.md)。

## 准备 Python 环境

本机重构项目已有 Python 3.11 的 `.venv`，可以直接使用项目解释器。在新机器上没有环境时，再在项目根目录创建并安装依赖：

```powershell
if (-not (Test-Path .venv)) {
    uv venv --python 3.11 .venv
}
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
```

依赖只安装到项目虚拟环境；直接使用 `.venv\Scripts\python.exe` 不需要先激活环境。Docker 镜像在 `/opt/venv` 内安装自己的依赖，不使用宿主机的 Windows `.venv`。

## 设置环境变量

Compose 通过 `.env` 进行变量替换，并通过 `env_file` 将配置传入应用。已有文件应保留；新机器可按需从模板创建：

```powershell
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
}
if (-not (Test-Path .env.test)) {
    Copy-Item .env.test.example .env.test
}
```

在 `.env` 填写数据库密码、模型密钥和至少 32 字符的随机 JWT 密钥；`.env.test` 使用另一份独立 JWT 密钥。

| 变量 | 用途 | 直接运行 Python 时的默认值 | Compose 正式 / 测试配置 |
| --- | --- | --- | --- |
| `DEEPSEEK_API_KEY` | DeepSeek 调用认证；未设置时客户端初始化会报错 | 无 | 从 `.env` 传入 |
| `PASSWORD` | PostgreSQL 密码 | 无 | 数据库与应用使用同一配置 |
| `JWT_SECRET_KEY` | 签发和校验一小时有效的登录 JWT | 无，至少 32 字符 | 正式取 `.env`，测试取 `.env.test` |
| `UAV_DB_NAME` | 数据库名称 | `uav_project` | `uav_project` / `uav_project_test` |
| `UAV_DB_HOST` | 数据库主机 | `localhost` | `postgres` |
| `UAV_DB_PORT` | 数据库端口 | 优先读取此变量，否则读取 `PORT`，最终为 `5433` | `5432` |
| `CELERY_BROKER_URL` | Celery 消息队列 | `redis://redis:6379/0` | Redis `/0` / `/3` |
| `CELERY_RESULT_BACKEND` | Celery 结果存储 | `redis://redis:6379/1` | Redis `/1` / `/4` |
| `REDIS_CACHE_URL` | 业务查询缓存 | `redis://redis:6379/2` | Redis `/2` / `/5` |
| `UAV_API_PORT` / `UAV_TEST_API_PORT` | Compose 映射到宿主机的 HTTP 端口 | 不控制本地 Uvicorn | 默认 `8002` / `8003` |
| `UAV_APP_IMAGE` | Compose 应用镜像名称 | 不用于直接运行 Python | 未设置时为 `uav-project-refactored:local` |

数据库用户为 `postgres`。主机和端口在 `src/database/connection.py` 中读取，并非固定值；兼容变量 `PORT` 只用于数据库连接，与 HTTP 端口无关。直接运行 Python 时，项目不会自动读取 `.env`，需在同一 PowerShell 终端用 `$env:变量名 = "值"` 设置配置，或由启动工具显式导入环境文件。密码和密钥不要提交到仓库。

## 服务地址与端口

| 服务 | 容器内地址 | 当前宿主机入口 |
| --- | --- | --- |
| 正式 API | `api:8000` | [登录页](http://127.0.0.1:8002/login)、[接口文档](http://127.0.0.1:8002/docs) |
| 测试 API | `api-test:8000` | [登录页](http://127.0.0.1:8003/login)、[接口文档](http://127.0.0.1:8003/docs) |
| PostgreSQL | `postgres:5432` | 默认不映射宿主机端口，通过 `docker compose exec postgres` 访问 |
| Redis | `redis:6379` | 默认不映射宿主机端口，通过 `docker compose exec redis` 访问 |

宿主机不能直接解析容器服务名 `postgres`、`redis`。如需在 Windows 运行 Python，应自行配置可从宿主机访问的数据库、Redis 地址及共享 CSV 目录；代码中的 `localhost:5433` 兼容默认值不代表当前已开放此端口。

Compose 自动设置 `CSV_UPLOAD_DIR=/app/upload_spool`、`UAV_LOG_DIR=/app/logs`、`HF_HOME=/models-cache`、`TIKTOKEN_CACHE_DIR=/tokenizer-cache`；初始化完成后，应用以 `HF_HUB_OFFLINE=1` 使用检索模型缓存。默认部署使用命名卷，本机缓存覆盖见 `compose.local.yaml`、`compose.test.local.yaml`。

## 准备数据库

统一入口为 `sql/init_database.sql`；原来的 `sql/PostgreSQL.sql` 文件名也会转到该入口。它按依赖顺序创建知识文档、用户、飞行器、飞行记录及任务相关表，并补齐当前的 `task_id`、`user_id` 等迁移。脚本不插入示例数据，可以重复执行。旧学习笔记保存在 `reference/PostgreSQL_legacy_notes.txt`，不再作为初始化程序运行。

`sql/create_documents.sql` 会在目标数据库启用 `vector` 扩展，并创建含 `id, content, source, metadata, embedding, created_at` 的 `documents` 表。当前模型对应 `vector(768)`；已有表缺字段或向量维度不符时明确报错，不自动改写已有资料。PostgreSQL 服务本身必须已安装 pgvector；当前容器使用 `pgvector/pgvector:pg17`，SQL 只负责在每个数据库启用扩展。

新 Compose 部署会通过 `db-init` 自动创建正式库和测试库并执行初始化。通过服务名连接或手动重复迁移：

```powershell
docker compose exec postgres psql -U postgres -d uav_project
docker compose exec postgres psql -U postgres -d uav_project_test
docker compose run --rm db-init
```

飞行表脚本现在兼容三种情况：空库直接建表；识别到旧结构时保留数据并归档为 `flight_records_legacy`；已有新结构时保留原表和数据。归档名称冲突或结构无法识别时停止，不覆盖现有表。已有旧结构时应先备份、完成旧任务并停止旧版 API 和 worker，再执行切换。完整初始化步骤及验证命令见 [sql/README.md](sql/README.md)；LangGraph 检查点表继续由 FastAPI 启动时的 `PostgresSaver.setup()` 管理。

## 接口入口

完整流程使用上面的 Docker 部署，默认从宿主机 8002 或 8003 访问。仅在已配置宿主机可访问的数据库、Redis 和环境变量时，才使用下面的本地 API 启动方式：

```powershell
.\.venv\Scripts\python.exe -m uvicorn api:app --reload --host 127.0.0.1 --port 8000
```

这条命令只启动本地 API，文档地址为 `http://127.0.0.1:8000/docs`；CSV 异步流程还需要 Celery worker 和共享暂存目录。主要接口如下：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/health` | 检查服务状态 |
| POST | `/flight/uavs` | 单独登记飞行器；重复 `uav_code` 返回 409 |
| GET | `/flight/uavs` | 登录后查看自己的飞行器 |
| GET | `/flight/uavs/{uav_id}/flights` | 按自己的飞行器系统 ID 查询记录 |
| POST | `/flight/flights/validate` | 校验一条 CSV 时间区间 |
| POST | `/ai_flight/flights/report` | 登录后上传 CSV 和幂等键，提交 Celery 任务；立即返回任务 ID |
| GET | `/ai_flight/report/jobs/{task_id}` | 登录后查询本人任务的状态及结果 |
| GET | `/flight/flights/{record_id}` | 按数据库生成的 ID 查询飞行记录 |
| GET | `/flight/flights?limit=5&uav_code=UAV-1` | 查询最近记录，可按飞行器编号筛选 |
| POST | `/ai_flight/flights/{record_id}/report/jobs` | 登录后携带 `Idempotency-Key` 请求头，提交单条报表任务 |

上传接口要求登录，并在 `multipart/form-data` 中传 `file` 和 `idempotency_key`（UUID）。聊天页的上传按钮会自动生成并提交幂等键；Postman 调用时需自行生成 UUID，并携带登录 Cookie 或 `Authorization: Bearer <JWT>`。先在数据库中占用 `(user_id, idempotency_key)`；同一用户重复使用该键返回 HTTP 409，响应体与首次提交一样使用顶层 `task_id`、`status`，其中 `task_id` 为原任务 ID，`status` 为当前任务状态；不同用户可以使用相同键。新文件应使用新键；若连接中断，重试同一文件应沿用原键。幂等键记录保留，不会自动过期。

`db-init` 已通过统一入口在两库执行 `sql/create_csv_upload_idempotency_keys.sql`，无需首次启动后再手动逐库建表。该表保存用户 ID、幂等键、任务 ID 和创建时间；手动重置测试环境时会被清空。

任务结果查询须携带登录 Cookie 或 `Authorization: Bearer <JWT>`，仅任务所属用户可以查询；其他用户和未知任务均返回 404。单条报表提交还须携带 `Idempotency-Key: <UUID>` 请求头；同一用户重复使用该键返回 409 和原任务 ID，若把同一个键用于另一条飞行记录也返回 409。统一初始化入口也包含 `sql/add_task_owner_and_report_idempotency.sql`，为任务状态添加用户 ID 并创建报表幂等表。旧 CSV 任务可通过已有上传幂等表核对归属；缺少任何归属记录的历史任务不能从此接口查询。

上传接口占用键后把文件暂存到 API 与 worker 共用的 `CSV_UPLOAD_DIR`，然后投递 `uav.process_flights_csv` 任务，返回 HTTP 202 和 `task_id`；它只在占用键时短暂借用 API 数据库连接。文件暂存失败会释放键；投递结果不确定时保留键和文件，并返回可查询的任务 ID，避免重试产生第二个任务。worker 读取暂存文件后先完成解析、校验、分组计算和逐组生成 AI 报告，所有报告成功后统一入库并清除列表缓存，在确认任务成功或失败后尝试删除暂存文件；租约丢失、等待重投时保留文件。通过 `GET /ai_flight/report/jobs/{task_id}` 查询任务状态及结果。

上传 CSV 需要 `uav_code,uav_model,manufacturer,flight_id,start_time,end_time,height,speed,battery,temperature`。每行是一段时间区间；同一 `uav_code` 和 `flight_id` 的行属于同一次飞行。时间必须写为 `YYYY-MM-DD HH:mm`，按北京时间解释，结束时间必须晚于开始时间，同组区间不能重叠。运行分钟数取该组最早开始到最晚结束的跨度，包含区间之间的空档。`flight_id` 仅用于本次分组，不写入数据库；新表的 `id` 由数据库生成。使用新幂等键重复上传允许生成新的飞行记录；同一用户沿用原幂等键不会重复创建任务。每组独立填值、插值，整份 CSV 的所有记录在同一事务中写入。示例：

```csv
uav_code,uav_model,manufacturer,flight_id,start_time,end_time,height,speed,battery,temperature
UAV-1,M1,Maker,flight-a,2026-10-28 10:00,2026-10-28 10:05,10,2,90,20
UAV-1,M1,Maker,flight-a,2026-10-28 10:10,2026-10-28 10:20,12,3,80,21
```

`uav_code` 在入库前去除首尾空白并转为大写，数据库中全局唯一。导入时只复用当前用户已有的飞行器，不更新型号或制造商；他人或无归属的旧编号不能认领。单独登记已有编号则报“飞行器 ID 重复”。仓库现有的 `data/data.csv` 仍是旧格式，缺少飞行器编号和起止时间，不能直接上传到这个新版接口。

Docker Compose 已为 API 和 worker 挂载同一个 `csv_uploads` 卷，二者必须使用相同的 `CSV_UPLOAD_DIR`。如果一个进程在宿主机、另一个在容器里运行，需要另外配置双方可见的共享目录；仅使用各自的默认临时目录无法传递文件。worker 异常退出或投递状态不明时可能留下暂存文件，需按文件标识检查并清理。Compose 的 model-init 会先准备检索模型和分词器缓存；成功后 API、worker 才使用共享缓存启动。

## Docker 日志

Compose 将日志挂载到当前项目的 `./logs`。级别 INFO，按北京时间每天分别写入 `fastapi-YYYY-MM-DD.log`、`worker-YYYY-MM-DD.log`；测试服务分别保存到 `logs/test-api`、`logs/test-worker`。原项目和重构项目各自保存自己的日志，不再互相复制。日志不自动清理。

## 问答接口与会话状态

问答接口的请求体示例：

```json
{"question": "最近一次飞行的最高速度是多少？"}
```

`POST /ai_flight/model` 和 `POST /ai_flight/assistant/model` 首次调用不传 `thread_id`，响应会返回一个新的 `thread_id`。下一轮把它原样传回去，例如：

```json
{"question": "那它的最低电量呢？", "thread_id": "上一轮响应中的 thread_id"}
```

Agent 的对话状态由 LangGraph `PostgresSaver` 保存在 PostgreSQL；同一个 `thread_id` 会恢复历史消息和摘要，未知编号返回 404。FastAPI 启动时会运行一次检查点表初始化，并在关闭时释放专用连接池。检查点池最多使用 2 条连接，原有 API 业务池上限仍为 5 条；数据库需要为同一 API 进程预留最多 7 条连接。命令行 `main.py` 演示仍使用内存检查点。

## 登录与 AI 文字对话

使用 Compose 启动时，`.env` 需含有 `JWT_SECRET_KEY`（至少 32 字符）；Compose 会将它传入 API 容器。本地直接运行 API 时，需在启动窗口设置相同的环境变量。浏览器访问 `/register` 注册，成功后返回 `/login`；登录成功跳转 `/chats`。新会话以首条提问作为标题，没有标题的历史会话仍显示会话编号。点击“新建 AI 对话”进入 `/chat/new`，首次提问成功后才把新的 `thread_id` 归到当前用户，并跳转到 `/chat?thread_id=...`。此后页面只需输入问题，服务端从 URL 读取 ID 并核对用户归属。

`POST /ai_flight/model` 和 `POST /ai_flight/assistant/model` 也要求登录。浏览器会自动携带 HttpOnly 登录 Cookie；直接调用 API 时可用 `Authorization: Bearer <JWT>`。两条接口对传入的 `thread_id` 执行相同的归属检查。JWT 只含 `user_id`、`user_name`、`iat`、`exp`，不含会话 ID。CSV 上传仍使用独立的接口；聊天页另有 CSV 上传按钮，报告不会进入当前聊天记录。

聊天页提交 CSV 后会显示处理状态，每 2 秒自动查询一次任务，完成后按飞行记录分别展示统计和报告，失败时显示具体原因。查询断网会自动重试，连续 3 次失败后可点击“继续查询”，不会再次上传文件。同一标签页会按用户和会话保存最近任务编号，刷新后恢复查询；报告内容仍从有归属校验的后端接口获取。页面交互测试通过 Node.js 内置测试运行器执行：`node --test tests/test_csv_upload_ui.cjs`。

## 运行知识问答、Agent 演示和检索评估

在当前 Docker 环境中，可复用 API 容器的数据库配置、模型缓存和依赖执行开发脚本：

```powershell
# 导入 data/uav_knowledge.json，会向正式库 documents 写入资料
docker compose exec -T api python -m examples.import_documents
```

重复导入会重复插入资料。检索使用 `intfloat/multilingual-e5-base`，重排使用 `BAAI/bge-reranker-base`；Web 与命令行演示都复用当前 Agent graph，`examples/rag_demo.py` 保留为该演示的兼容入口。

`main.py` 委托给 `examples/agent_demo.py`，使用内存检查点，不经过 Web 登录。通过 `--user-id` 显式提供已有用户 ID，演示会设置对应的 `use_data_user()` 作用域。以下 `1` 仅为示例，应换成当前数据库中的合法用户 ID：

```powershell
.\.venv\Scripts\python.exe main.py --user-id 1 --question "无人机什么时候需要返航？"
.\.venv\Scripts\python.exe -m examples.agent_demo --user-id 1
```

交互式多轮对话使用登录后的聊天页。在 Windows `.venv` 中运行实验脚本前，还需按上文配置宿主机可访问的数据库、Redis 和模型缓存。使用 `main.py --help` 查看参数不会加载模型或要求模型密钥。

评估用例来自 `data/rag_test_cases.json`。评估函数位于 `src/rag/evaluation.py`；调用时需传入 `embedding_model`，重排评估还需传入 `rerank_model`。两种评估共用 `calculate_metrics()`，保留原来的计算含义：

- `mean_recall`：至少命中一次期望主题的问题占比。这里沿用原项目的名称，计算的是主题命中率。
- `mean_precision`：每个问题中，期望主题的资料占检索结果的比例，再对全部问题取平均。
- `mean_mrr`：第一条命中资料的排名倒数，再对全部问题取平均。

没有检索结果时，该问题的三个指标均为 0。评估用例为空时显示提示，三个指标均显示为 0。检索距离筛选和重新排序规则保持原有设置。

## 更新飞行记录（乐观锁）

飞行器和飞行记录的查询、登记、更新均要求登录。上传时的用户编号来自 JWT；worker 从任务表恢复同一用户身份，CSV、URL 和模型参数不能指定数据所有者。普通查询与 Agent 工具都只返回该用户拥有的数据，Redis 缓存按用户隔离。

先调用 `GET /flight/uavs` 查看自己的飞行器，再用返回的系统 `id` 调用 `GET /flight/uavs/{uav_id}/flights?limit=5` 查询对应记录。旧的按记录 ID、编号或最近记录查询入口也执行相同的归属过滤；访问他人数据统一返回 404 或空列表，不能通过报表任务绕过检查。`uav_code` 仍全局唯一，导入只能复用自己的飞行器，不能自动认领他人的编号或无归属的旧编号。

`db-init` 的统一入口已包含 `sql/add_flight_data_ownership.sql`，两库使用同一套结构。迁移只根据一致的任务归属补齐用户，无法确定的旧数据保留为空归属并隐藏；新增记录必须带用户，复合外键保证飞行记录与飞行器属于同一用户。升级旧结构前应备份并停下旧版 API、worker，再启动配套新代码。独立脚本若要访问飞行数据，也需要在 `use_data_user(合法用户ID)` 上下文中运行，不存在默认访问全部用户数据的身份。

权限隔离测试使用 `.\.venv\Scripts\python.exe -m pytest tests/test_data_permissions.py`。当前容器内的真实 JWT、API 和 CSV 队列联调方法见下文“运行已有测试”。

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
.\.venv\Scripts\python.exe -m pytest tests verification -q
```

`tests` 主要使用假连接、缓存和模型响应验证业务行为；真实数据库用例需要显式启用，默认测试不会重置日常数据库。部分配置用例会调用本机 Docker Compose 解析配置。

当前 PostgreSQL 服务运行时，可选择验证空库初始化；用例仅创建并回收自己随机命名的临时库：

```powershell
$env:RUN_DATABASE_SCHEMA_TESTS = "1"
.\.venv\Scripts\python.exe -m pytest verification/test_database_initialization.py -q
Remove-Item Env:\RUN_DATABASE_SCHEMA_TESTS
```

测试库已有至少两个用户时，可在测试 API 容器中验证 JWT、用户归属和真实 CSV 队列：

```powershell
docker compose -f compose.yaml -f compose.test.yaml exec -T api-test python verification/check_ownership_stack.py
```

该联调脚本会在测试库新增一条缺列 CSV 的失败任务及对应幂等键，不调用外部 LLM，也不新增飞行记录。

`verification/test_ownership_database.py` 是另一个可选的实库权限用例，默认跳过。它从运行环境读取 `UAV_DB_HOST`、`UAV_DB_PORT`（兼容 `PORT`）、`UAV_DB_NAME` 和 `PASSWORD`；默认地址为 Compose 内的 `postgres:5432`，且连接前要求库名明确为 `uav_project_test`，禁止误连正式库。用例创建的示例行在外层事务结束时回滚，不会清空测试库。

当前数据库未发布宿主机端口，因此应在 Compose 网络内运行此用例。以下命令适用于本机的四份 Compose 配置：创建临时测试容器、挂载当前验证代码，并只在该临时容器的虚拟环境中安装 pytest；运行结束后删除临时容器，不改动正在运行的 API 容器。此用例不调用外部 LLM。

```powershell
docker compose -f compose.yaml -f compose.test.yaml -f compose.local.yaml -f compose.test.local.yaml run --rm --no-deps -e RUN_OWNERSHIP_DB_TEST=1 -v "./verification:/app/verification:ro" api-test sh -c "uv pip install --python /opt/venv/bin/python pytest==9.1.1 && python -m pytest -p no:cacheprovider verification/test_ownership_database.py -q"
```

仅使用基础 Compose 的环境可去掉两个 `local` 文件参数；执行前需已启动 PostgreSQL 并完成测试库初始化。日常基础测试不需要启用此实库用例，完整业务联调也可以通过 Postman 手动完成。

本机当前使用 E 盘模型缓存，手动重置测试环境时沿用相同配置；不加 `-Execute` 只预览：

```powershell
.\scripts\reset_test_environment.ps1 -UseLocalCache
.\scripts\reset_test_environment.ps1 -UseLocalCache -Execute
```

清理仅处理测试库数据、Redis `/3～/5` 和测试 CSV，保留表结构、检查点迁移记录、日志及数据卷；会轮换测试 JWT，清理后需重新注册测试用户。正式库、正式 Redis `/0～/2` 和正式 CSV 不在清理范围内。


## 关键代码位置

- Web 应用和生命周期：`app/app.py`；兼容入口：`api.py`。
- CSV 任务：`app/tasks.py`；暂存和清理：`app/csv_upload.py`、`app/task_lease.py`。
- Agent graph：`src/agent/graph/graph.py`；摘要节点：`src/agent/graph/nodes/summary_node.py`。
- RAG 工具：`src/agent/tools/rag_search.py`；数据库连接：`src/database/connection.py`。
