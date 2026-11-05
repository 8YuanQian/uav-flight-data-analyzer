# 数据库初始化与旧表切换

在项目根目录使用 `psql -f sql/init_database.sql`，或沿用 `sql/PostgreSQL.sql`。两者使用同一入口，相对引用以脚本目录为准。不要通过只复制单个入口文件到容器的方式执行，整个 `sql` 目录都需要可读。

## 前提与执行顺序

新 Compose 部署由 `db-init` 服务先创建正式库和测试库，再执行本目录入口。数据库服务只读挂载本目录到 `/schema`，不需要按容器名复制文件；可用 `docker compose run --rm db-init` 手动重跑。下面的“目标库已存在”是单独使用 SQL 入口时的前提。

- 目标数据库已存在，连接账号有建表和启用扩展的权限。
- PostgreSQL 服务已安装 pgvector。当前项目容器为 `pgvector/pgvector:pg17`；普通 PostgreSQL 镜像需要先安装扩展二进制。
- 扩展在每个目标数据库分别启用，见 [pgvector 官方说明](https://github.com/pgvector/pgvector#getting-started)。

入口按以下顺序执行：

1. `create_documents.sql`：启用 `vector`，建立 `documents`，检查已有表字段与 768 维向量类型。
2. `create_users_and_password.sql`：建立用户、密码哈希和会话标题表，以及用户名索引。
3. `create_uavs_and_new_flight_records.sql`：创建或切换飞行基础表。
4. `add_import_task_ids.sql`：补齐飞行数据的任务来源字段。
5. `create_csv_upload_idempotency_keys.sql`、`create_celery_task_states.sql`：建立上传去重和任务状态表。
6. `add_task_owner_and_report_idempotency.sql`：补齐任务用户归属和单条报表去重表。
7. `add_flight_data_ownership.sql`：补齐飞行器、飞行记录的用户归属及约束。

这些脚本不创建数据库、不插入示例用户或飞行数据，也不创建废弃的 `flight_analyses`、`test_documents`。LangGraph 的检查点表由 FastAPI 启动时的 `PostgresSaver.setup()` 创建或升级。执行出错会立即停止，排除错误后可重跑入口。

## 飞行表的切换规则

- 没有 `flight_records`：直接创建基础新表，无需先造旧表。
- 有 `uav_id` 和 `duration_minutes`：视为新结构，检查基础字段后复用。
- 有 `flight_id` 和 `duration_seconds`：识别为旧结构，只归档一次，再创建空的新表。
- 旧表与 `flight_records_legacy` 同时存在，或已有结构无法识别：事务报错回滚，不覆盖、不删除数据。
- 归档表已存在但当前表已经是新版：允许重跑，保留两张表。

已有旧结构时先备份、完成旧队列任务并停止旧版 API 和 worker，再执行切换。脚本保留归档行，不自动把旧行转换为新业务记录。单独执行飞行表脚本只处理基础结构；完整业务所需的 `task_id`、`user_id` 及相关约束由初始化入口的后续迁移补齐。

知识文档表字段与当前存储代码一致：`content` 为必填文本，`source` 为来源，`metadata` 为 JSONB，`embedding` 为 `vector(768)`，`created_at` 默认当前时间。更换输出维度不同的模型时，需要另行迁移向量数据；脚本不会自动转换或丢弃已有向量。

历史演示笔记位于 `reference/PostgreSQL_legacy_notes.txt`；`add_flight_analyses_version.sql` 和 `scripts/init_flight_records.py` 用于已停用的旧结构，不在新库初始化流程中执行。

## 复现验证

Compose 的 `postgres` 服务运行时，在项目环境执行：

```powershell
$env:RUN_DATABASE_SCHEMA_TESTS = '1'
.\.venv\Scripts\python.exe -m pytest verification/test_database_initialization.py -q
```

用例创建随机命名的临时库，验证空库、旧表归档、重复执行、已有数据保留、错误维度及归档冲突，并在结束时删除各自创建的临时库。不会连接或重置日常业务库。测试库清理脚本把旧库可能存在的历史表视为可选项，新库不依赖这些废弃表。
