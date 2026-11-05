# 真实 PostgreSQL/pgvector 验证；每个用例只使用自己创建的临时空库。
import os
import re
import subprocess
import shlex
from types import SimpleNamespace
from uuid import uuid4

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_SCHEMA_TESTS") != "1",
    reason="显式设置 RUN_DATABASE_SCHEMA_TESTS=1 后才创建临时验证库",
)
# 可通过环境变量选择独立验证项目；目标仍由 Compose 的 postgres 服务确定。
COMPOSE = ["compose", *shlex.split(os.getenv("UAV_SCHEMA_COMPOSE_ARGS", "-f compose.yaml"))]


def docker(*arguments, sql=None, success=True):
    result = subprocess.run(
        ["docker", *arguments], input=sql, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    if success:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.fixture(scope="module")
def sql_directory():
    # 主配置已只读挂载完整 SQL 目录，无需按固定容器名复制脚本。
    return "/schema"


@pytest.fixture
def database(sql_directory):
    name = "uav_schema_test_" + uuid4().hex
    docker(*COMPOSE, "exec", "-T", "postgres", "createdb", "-U", "postgres", "-T", "template0", name)

    def execute(sql=None, filename=None, success=True):
        arguments = [
            *COMPOSE, "exec", "-T", "postgres", "psql", "-U", "postgres", "-d", name,
            "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1",
        ]
        if filename:
            arguments += ["-f", sql_directory + "/" + filename]
        return docker(*arguments, sql=sql, success=success)

    try:
        yield SimpleNamespace(run=execute, name=name)
    finally:
        # 不接收环境变量作为删除目标，绝不能清理正式库或日常测试库。
        assert re.fullmatch(r"uav_schema_test_[0-9a-f]{32}", name)
        docker(*COMPOSE, "exec", "-T", "postgres", "dropdb", "-U", "postgres", "--if-exists", "--force", name)


def query(database, sql):
    return database.run(sql=sql).stdout.strip()


def test_fresh_bootstrap_creates_current_tables_and_usable_vector_search(database):
    # 原文件名也必须是可执行入口，而不是混入 PowerShell 的笔记。
    database.run(filename="PostgreSQL.sql")
    assert query(database, "SELECT count(*) FROM pg_extension WHERE extname='vector'") == "1"
    tables = set(query(database, "SELECT tablename FROM pg_tables WHERE schemaname='public'").splitlines())
    assert tables == {
        "documents", "users", "password", "chat_titles", "uavs", "flight_records",
        "csv_upload_idempotency_keys", "celery_task_states", "flight_report_idempotency_keys",
    }
    assert query(database, """
        SELECT format_type(atttypid,atttypmod) FROM pg_attribute
        WHERE attrelid='public.documents'::regclass AND attname='embedding'
    """) == "vector(768)"
    database.run(sql="""
        INSERT INTO documents(content,source,metadata,embedding)
        VALUES('schema-document','synthetic','{"type":"schema"}',
               ('[1' || repeat(',0',767) || ']')::vector);
    """)
    # 与检索函数一样，使用元数据过滤和余弦距离，且不调用任何模型。
    assert query(database, """
        SELECT content FROM documents WHERE metadata->>'type'='schema'
        ORDER BY embedding <=> ('[1' || repeat(',0',767) || ']')::vector LIMIT 1
    """) == "schema-document"
    assert query(database, """
        SELECT embedding <=> ('[1' || repeat(',0',767) || ']')::vector FROM documents
    """) == "0"
    database.run(filename="init_database.sql")
    assert query(database, "SELECT count(*) FROM documents") == "1"


def test_flight_script_alone_works_without_old_table_and_can_repeat(database):
    database.run(filename="create_uavs_and_new_flight_records.sql")
    database.run(filename="create_uavs_and_new_flight_records.sql")
    assert query(database, "SELECT to_regclass('public.flight_records_legacy') IS NULL") == "t"
    assert query(database, "SELECT count(*) FROM flight_records") == "0"
    assert query(database, "SELECT count(*) FROM uavs") == "0"


def create_legacy(database):
    database.run(sql="""
        CREATE TABLE flight_records(id BIGSERIAL PRIMARY KEY,flight_id TEXT,duration_seconds INTEGER);
        INSERT INTO flight_records(flight_id,duration_seconds) VALUES('legacy-flight',900);
    """)


def test_old_flight_table_is_archived_once_without_losing_data(database):
    create_legacy(database)
    database.run(filename="init_database.sql")
    database.run(filename="init_database.sql")
    assert query(database, "SELECT flight_id||':'||duration_seconds FROM flight_records_legacy") == "legacy-flight:900"
    assert query(database, "SELECT count(*) FROM flight_records") == "0"


def test_current_owned_rows_survive_repeated_bootstrap(database):
    database.run(filename="init_database.sql")
    database.run(sql="""
        WITH actor AS (
            INSERT INTO users(username) VALUES('schema-user') RETURNING id
        ), aircraft AS (
            INSERT INTO uavs(uav_code,uav_model,manufacturer,user_id)
            SELECT 'SCHEMA-UAV','Model','Maker',id FROM actor RETURNING id,user_id
        )
        INSERT INTO flight_records(
            uav_id,user_id,filename,start_time,end_time,duration_minutes,row_count,
            average_height,max_height,average_speed,max_speed,battery_start,battery_end,
            minimum_battery,average_temperature,max_temperature,anomaly_status
        )
        SELECT id,user_id,'schema.csv','2026-01-01 10:00+08','2026-01-01 10:30+08',
               30,2,20,25,8,10,90,80,80,25,27,'normal' FROM aircraft;
    """)
    before = query(database, "SELECT row_to_json(f) FROM flight_records AS f")
    database.run(filename="init_database.sql")
    assert query(database, "SELECT row_to_json(f) FROM flight_records AS f") == before
    assert query(database, "SELECT count(*) FROM uavs") == "1"
    assert query(database, "SELECT count(*) FROM users") == "1"


def test_existing_archive_conflict_stops_without_overwriting_either_table(database):
    create_legacy(database)
    database.run(sql="CREATE TABLE flight_records_legacy(note TEXT); INSERT INTO flight_records_legacy VALUES('keep-archive')")
    result = database.run(filename="create_uavs_and_new_flight_records.sql", success=False)
    assert result.returncode != 0
    assert "归档已存在" in result.stderr
    assert query(database, "SELECT flight_id FROM flight_records") == "legacy-flight"
    assert query(database, "SELECT note FROM flight_records_legacy") == "keep-archive"
    assert query(database, "SELECT to_regclass('public.uavs') IS NULL") == "t"


def test_unrecognized_flight_structure_is_not_renamed(database):
    database.run(sql="CREATE TABLE flight_records(note TEXT); INSERT INTO flight_records VALUES('keep')")
    result = database.run(filename="create_uavs_and_new_flight_records.sql", success=False)
    assert result.returncode != 0
    assert "无法识别" in result.stderr
    assert query(database, "SELECT note FROM flight_records") == "keep"
    assert query(database, "SELECT to_regclass('public.flight_records_legacy') IS NULL") == "t"


def test_incompatible_vector_dimension_stops_without_replacing_document_data(database):
    database.run(sql="""
        CREATE EXTENSION vector;
        CREATE TABLE documents(id BIGSERIAL PRIMARY KEY,content TEXT,source TEXT,
            metadata JSONB,embedding vector(3),created_at TIMESTAMPTZ);
        INSERT INTO documents(content,embedding) VALUES('keep-document','[1,0,0]');
    """)
    result = database.run(filename="create_documents.sql", success=False)
    assert result.returncode != 0
    assert "必须为 vector(768)" in result.stderr
    assert query(database, "SELECT content FROM documents") == "keep-document"


def test_incomplete_existing_documents_has_clear_error_without_data_loss(database):
    database.run(sql="""
        CREATE EXTENSION vector;
        CREATE TABLE documents(content TEXT,embedding vector(768));
        INSERT INTO documents(content) VALUES('keep-document');
    """)
    result = database.run(filename="create_documents.sql", success=False)
    assert result.returncode != 0
    assert "缺少字段" in result.stderr
    assert query(database, "SELECT content FROM documents") == "keep-document"

