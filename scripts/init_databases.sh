#!/bin/sh
# 只用于本项目管理的 PostgreSQL；先建两个库，再重复执行当前结构迁移。
set -eu
export PGHOST=postgres PGPORT=5432 PGUSER=postgres
: "${PGPASSWORD:?必须配置数据库密码}"

psql -X -d postgres -v ON_ERROR_STOP=1 <<'SQL'
SELECT format('CREATE DATABASE %I', name)
FROM (VALUES ('uav_project'), ('uav_project_test')) AS databases(name)
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = name)
\gexec
SQL

for database in uav_project uav_project_test; do
    psql -X -d "$database" -v ON_ERROR_STOP=1 -f /schema/init_database.sql
done
