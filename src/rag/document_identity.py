# 以来源和原文生成稳定的片段标识，不依赖数据库自增 ID 或主题名称。
import hashlib
import json

from src.rag.chunk import chunk_content

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


def document_id(document: dict) -> str:
    identity = json.dumps(
        [document.get("source"), document["content"]],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def corpus_chunks(documents: list[dict]) -> list[dict]:
    # 与现有知识文档导入的切片方式一致；不添加 query 或 passage 前缀。
    return [
        {**document, "content": chunk}
        for document in documents
        for chunk in chunk_content(document["content"], CHUNK_SIZE, CHUNK_OVERLAP)
    ]
