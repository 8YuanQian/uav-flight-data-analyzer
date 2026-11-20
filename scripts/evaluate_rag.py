# 运行冻结语料评估，不调用生成式 LLM，不写入业务表或现有 documents 表。
import argparse
from contextlib import contextmanager, nullcontext
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.rag.config import DEFAULT_RETRIEVAL_CONFIG, RetrievalConfig
from src.rag.document_identity import corpus_chunks, document_id
from src.rag.embedding import EMBEDDING_ENCODINGS, LEGACY_ENCODING, create_passage_embeddings
from src.rag.evaluation import evaluate_case, load_test_cases, summarize_results


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git_commit():
    # 精简运行镜像可能没有 Git，仍能依靠逐文件指纹追溯评估代码。
    try:
        result = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                capture_output=True, text=True)
    except FileNotFoundError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def validate_inputs(dataset, corpus, manifest_path):
    manifest = read_json(manifest_path)
    if file_hash(dataset) != manifest["dataset_sha256"]:
        raise ValueError("问题集与冻结清单不一致，请先复核标注并更新清单")
    if file_hash(corpus) != manifest["corpus_sha256"]:
        raise ValueError("知识语料与冻结清单不一致，请先重新核对相关片段标注")
    cases = load_test_cases(dataset, corpus)
    if manifest["question_count"] != len(cases):
        raise ValueError("冻结清单的问题数量不一致")
    return cases, corpus_chunks(read_json(corpus)), manifest


@contextmanager
def evaluation_connection(mode, chunks, embedding_model, *, encoding=LEGACY_ENCODING):
    from psycopg.types.json import Jsonb
    from src.database.connection import get_connection

    # 持久语料未附带可验证的编码版本；前缀对照必须从同一原文重建临时向量。
    if mode == "database" and encoding != LEGACY_ENCODING:
        raise ValueError("E5 前缀评估请使用 temporary 模式重新编码文档")
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            database_name = cursor.fetchone()[0]
            if mode == "temporary":
                if database_name != "uav_project_test":
                    raise ValueError("临时评估只允许连接 uav_project_test")
                # 会话内临时表遮蔽同名持久表；退出时回滚并关闭连接。
                cursor.execute("SET LOCAL search_path TO pg_temp, public")
                cursor.execute("""CREATE TEMP TABLE documents (
                    id bigint GENERATED ALWAYS AS IDENTITY,
                    content text NOT NULL, source text, metadata jsonb,
                    embedding vector(768) NOT NULL
                ) ON COMMIT DROP""")
                vectors = create_passage_embeddings(
                    [doc["content"] for doc in chunks], embedding_model, encoding=encoding, batch_size=8,
                    show_progress_bar=False,
                )
                cursor.executemany(
                    "INSERT INTO pg_temp.documents (content, source, metadata, embedding) "
                    "VALUES (%s, %s, %s, %s::vector)",
                    [(doc["content"], doc.get("source"), Jsonb(doc.get("metadata", {})),
                      vector.tolist()) for doc, vector in zip(chunks, vectors)],
                )
            else:
                # 直接评估现有语料时强制只读，并要求与冻结片段完全匹配。
                connection.rollback()
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cursor.execute("SELECT content, source FROM documents ORDER BY id")
            stored_ids = [document_id({"content": row[0], "source": row[1]})
                          for row in cursor.fetchall()]
            if sorted(stored_ids) != sorted(document_id(doc) for doc in chunks):
                raise ValueError("数据库语料与冻结语料不一致，禁止把不一致的结果当作对照")
        try:
            # 复用同一个会话，保证检索始终访问上述临时表或同一只读快照。
            yield lambda: nullcontext(connection), database_name
        finally:
            connection.rollback()


def comparison_markdown(summary, config):
    quality = summary["quality"]
    lines = [
        "# RAG 重排前后对照", "",
        f"向量编码方式：`{config.encoding}`。质量每题统计一次，延迟包含全部重复运行。",
        "候选为向量检索经距离阈值筛选后的同一集合；排序对照不应用重排分数阈值。",
        "向量总耗时与重排总耗时共用同次检索耗时，属于配对测量。", "",
        "| 对照 | Hit@K | Precision@K | Recall@K | MRR@K | 无答案误召回率 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for key, label in (("ranking_vector", "只按向量排序"),
                       ("ranking_reranked", "增加重排，仅比较排序"),
                       ("runtime_reranked", "增加重排及运行阈值")):
        item = quality[key]
        values = [item[f"hit@{config.final_k}"], item[f"precision@{config.final_k}"], item[f"recall@{config.final_k}"],
                  item[f"mrr@{config.final_k}"], item["unanswerable_false_positive_rate"]]
        lines.append("| " + label + " | " + " | ".join(
            "—" if value is None else f"{value:.4f}" for value in values
        ) + " |")
    lines.extend(["", f"K = {config.final_k}；候选上限 = {config.candidate_k}。",
                  "无答案问题不计入 Hit、Recall、MRR；空分母保存为 null。", "",
                  "| 延迟阶段 | P50（毫秒） | P95（毫秒） |", "|---|---:|---:|"])
    for name, values in summary["latency_ms"].items():
        lines.append(f"| {name} | {values['p50']:.2f} | {values['p95']:.2f} |")
    lines.extend(["", "首版标注尚未经独立人工复核，召回率只对已标注片段有效。",
                  "本次未调参；完整测试集结果仅作基线，后续只用 dev 调参。",
                  "统计受当前 CPU、并发负载及小样本影响，不代表线上性能承诺。", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="冻结语料的 RAG 效果与延迟评估")
    parser.add_argument("--dataset", type=Path, default=ROOT / "data/rag_test_cases.json")
    parser.add_argument("--corpus", type=Path, default=ROOT / "data/uav_rag_knowledge_base_200.json")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/rag_eval_manifest.json")
    parser.add_argument("--output", type=Path, default=ROOT / "evaluation_results/rag")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--corpus-mode", choices=("temporary", "database"), default="temporary")
    parser.add_argument("--encoding", choices=EMBEDDING_ENCODINGS, default=LEGACY_ENCODING)
    parser.add_argument("--split", choices=("all", "dev", "test"), default="all")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--candidate-k", type=int, default=DEFAULT_RETRIEVAL_CONFIG.candidate_k)
    parser.add_argument("--final-k", type=int, default=DEFAULT_RETRIEVAL_CONFIG.final_k)
    parser.add_argument("--max-distance", type=float, default=DEFAULT_RETRIEVAL_CONFIG.max_cosine_distance)
    parser.add_argument("--min-score", type=float, default=DEFAULT_RETRIEVAL_CONFIG.min_rerank_score)
    args = parser.parse_args()
    if args.repeats < 1 or args.warmup < 0 or args.threads < 1:
        parser.error("重复次数、线程数必须为正数，预热次数不能为负数")
    if args.corpus_mode == "database" and args.encoding != LEGACY_ENCODING:
        parser.error("E5 前缀评估请使用 --corpus-mode temporary")
    config = RetrievalConfig(args.candidate_k, args.max_distance, args.final_k, args.min_score, encoding=args.encoding)
    cases, chunks, manifest = validate_inputs(args.dataset, args.corpus, args.manifest)
    if args.split != "all":
        cases = [case for case in cases if case["split"] == args.split]
    if not cases:
        parser.error("所选分组没有问题")
    print(f"校验通过：{len(cases)} 个问题，{len(chunks)} 个冻结片段。", flush=True)
    if args.validate_only:
        return

    # 延迟对照固定为 CPU，线程数明确记录；不会改动服务进程的模型设置。
    import torch
    from sentence_transformers import CrossEncoder, SentenceTransformer

    torch.set_num_threads(args.threads)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    output = args.output / run_id
    output.mkdir(parents=True, exist_ok=False)
    source_files = list((ROOT / "src/rag").glob("*.py")) + [Path(__file__).resolve(),
                    ROOT / "src/agent/tools/rag_search.py"]
    run_config = {
        "status": "running", "run_id": run_id, "retrieval": asdict(config),
        "dataset_version": manifest["version"],
        "dataset_sha256": file_hash(args.dataset), "corpus_sha256": file_hash(args.corpus),
        "encoding": config.encoding, "chunk_size": 500, "chunk_overlap": 50,
        "split": args.split, "question_count": len(cases), "repeats": args.repeats,
        "warmup": args.warmup, "corpus_mode": args.corpus_mode,
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "device": "cpu", "torch_threads": args.threads,
                        "packages": {name: version(name) for name in
                                     ("torch", "sentence-transformers", "psycopg")}},
        "git_commit": git_commit(),
        "source_sha256": {str(path.relative_to(ROOT)): file_hash(path) for path in source_files},
        "label_caveat": manifest["label_caveat"],
    }
    config_path = output / "config.json"

    def save_config():
        config_path.write_text(json.dumps(run_config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    save_config()
    try:
        started = perf_counter()
        embedding_model = SentenceTransformer("intfloat/multilingual-e5-base", device="cpu")
        rerank_model = CrossEncoder("BAAI/bge-reranker-base", device="cpu")
        run_config["model_load_ms"] = (perf_counter() - started) * 1000
        run_config["models"] = {
            "embedding": {"name": "intfloat/multilingual-e5-base", "revision":
                          getattr(embedding_model[0].auto_model.config, "_commit_hash", None)},
            "reranker": {"name": "BAAI/bge-reranker-base", "revision":
                         getattr(rerank_model.model.config, "_commit_hash", None)},
        }
        print("本地模型已加载，准备隔离评估语料。", flush=True)
        prepared = perf_counter()
        rows = []
        with evaluation_connection(args.corpus_mode, chunks, embedding_model, encoding=config.encoding) as (connect, database):
            run_config["database"] = database
            run_config["corpus_prepare_ms"] = (perf_counter() - prepared) * 1000
            for _ in range(args.warmup):
                evaluate_case(cases[0], embedding_model, rerank_model,
                              config=config, connection_factory=connect)
            print("预热完成，开始逐题对照。", flush=True)
            with (output / "per_query.jsonl").open("w", encoding="utf-8") as stream:
                for repetition in range(1, args.repeats + 1):
                    for index, case in enumerate(cases, 1):
                        row = evaluate_case(case, embedding_model, rerank_model,
                                            config=config, connection_factory=connect)
                        row["repetition"] = repetition
                        rows.append(row)
                        stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                        stream.flush()
                        if index % 10 == 0:
                            print(f"第 {repetition} 轮：{index}/{len(cases)}", flush=True)
        summary = summarize_results(rows, config)
        (output / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8",
        )
        (output / "comparison.md").write_text(comparison_markdown(summary, config), encoding="utf-8")
        run_config["status"] = "complete"
        save_config()
        print(f"评估完成：{output}", flush=True)
    except Exception as exc:
        run_config.update(status="failed", error_type=type(exc).__name__)
        save_config()
        raise


if __name__ == "__main__":
    main()
