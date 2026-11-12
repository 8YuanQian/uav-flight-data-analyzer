-- 使用 psql -f 执行；相对引用以本文件所在目录为准。
-- 目标数据库必须已创建，数据库服务必须已安装 pgvector。
\set ON_ERROR_STOP on
SET search_path = public;
\ir create_documents.sql
\ir create_users_and_password.sql
\ir create_uavs_and_new_flight_records.sql
\ir add_import_task_ids.sql
\ir create_csv_upload_idempotency_keys.sql
\ir create_celery_task_states.sql
\ir add_task_owner_and_report_idempotency.sql
\ir add_flight_data_ownership.sql
\ir add_flight_id.sql
-- LangGraph 检查点表继续由 FastAPI 启动时的 PostgresSaver.setup() 创建和升级。
