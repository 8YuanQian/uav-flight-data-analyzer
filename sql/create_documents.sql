-- 当前 embedding 模型输出 768 维；这里只启用已安装的 pgvector，不下载扩展二进制。
BEGIN;
SET LOCAL search_path = public;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector') THEN
        RAISE EXCEPTION 'PostgreSQL 服务尚未安装 pgvector，请先安装扩展或使用 pgvector/pgvector 镜像';
    END IF;
END
$$;
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

CREATE TABLE IF NOT EXISTS public.documents (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    content TEXT NOT NULL,
    source TEXT,
    metadata JSONB,
    embedding public.vector(768),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 不自动改写已有向量，避免维度不一致时误损坏知识库数据。
DO $$
DECLARE
    missing_columns text[];
    embedding_type text;
BEGIN
    SELECT array_agg(required.name ORDER BY required.name) INTO missing_columns
    FROM unnest(ARRAY['id', 'content', 'source', 'metadata', 'embedding', 'created_at']) AS required(name)
    WHERE NOT EXISTS (
        SELECT 1 FROM information_schema.columns AS actual
        WHERE actual.table_schema = 'public' AND actual.table_name = 'documents'
          AND actual.column_name = required.name
    );
    IF missing_columns IS NOT NULL THEN
        RAISE EXCEPTION '已有 documents 表缺少字段：%，请先迁移现有表，脚本未删除数据', missing_columns;
    END IF;
    SELECT format_type(atttypid, atttypmod) INTO embedding_type
    FROM pg_attribute
    WHERE attrelid = 'public.documents'::regclass AND attname = 'embedding' AND NOT attisdropped;
    IF embedding_type IS DISTINCT FROM 'vector(768)' THEN
        RAISE EXCEPTION 'documents.embedding 必须为 vector(768)，当前是 %；请先迁移向量数据', embedding_type;
    END IF;
END
$$;
COMMIT;
