import json
from pathlib import Path
from statistics import mean

from src.rag.config import DEFAULT_RETRIEVAL_CONFIG
from src.rag.document_identity import corpus_chunks, document_id
from src.rag.pipeline import run_retrieval


def load_test_cases(test_file, corpus_file=None):
    cases = json.loads(Path(test_file).read_text(encoding="utf-8-sig"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("评估集必须是非空问题列表")
    known_ids = None
    if corpus_file is not None:
        corpus = json.loads(Path(corpus_file).read_text(encoding="utf-8-sig"))
        known_ids = {document_id(doc) for doc in corpus_chunks(corpus)}
    seen, group_splits = set(), {}
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("每条评估问题必须是对象")
        for name in ("id", "question", "category", "group_id"):
            if not isinstance(case.get(name), str) or not case[name].strip():
                raise ValueError(f"评估问题缺少有效的 {name}")
        if case["id"] in seen:
            raise ValueError("评估问题编号重复")
        seen.add(case["id"])
        if type(case.get("answerable")) is not bool:
            raise ValueError("answerable 必须是布尔值")
        relevant = case.get("relevant_doc_ids")
        if not isinstance(relevant, list) or any(not isinstance(key, str) for key in relevant):
            raise ValueError("relevant_doc_ids 必须是字符串列表")
        if case["answerable"] != bool(relevant):
            raise ValueError("可回答问题必须有标注，无答案问题必须没有相关片段")
        negative = case.get("hard_negative_doc_ids", [])
        if not isinstance(negative, list) or any(not isinstance(key, str) for key in negative):
            raise ValueError("干扰片段编号必须是字符串列表")
        if set(relevant) & set(negative):
            raise ValueError("正确片段和干扰片段不能重叠")
        if known_ids is not None and (set(relevant) | set(negative)) - known_ids:
            raise ValueError(f"问题 {case['id']} 标注的片段不在冻结语料中")
        split = case.get("split")
        if split not in ("dev", "test"):
            raise ValueError("split 必须为 dev 或 test")
        previous = group_splits.setdefault(case["group_id"], split)
        if previous != split:
            raise ValueError("同一意图的改写问题不能跨调参集和测试集")
    return cases


def score_question(case, documents, k):
    # 标注与统计都按片段去重；主题仅用于分组展示，不作为正确性依据。
    keys = [doc.get("doc_id") or document_id(doc) for doc in documents[:k]]
    relevant = set(case["relevant_doc_ids"])
    if not case["answerable"]:
        return {"false_positive": bool(keys), "returned_count": len(keys)}
    ranks = [rank for rank, key in enumerate(keys, 1) if key in relevant]
    matches = len(set(keys) & relevant)
    return {
        "hit": bool(ranks),
        "precision": matches / k,
        "recall": matches / len(relevant),
        "reciprocal_rank": 1 / ranks[0] if ranks else 0.0,
        "returned_count": len(keys),
    }


def calculate_metrics(results, k=DEFAULT_RETRIEVAL_CONFIG.final_k):
    # results 每项为 {case: 标注问题, documents: 返回片段}。
    positive, negative = [], []
    for item in results:
        score = score_question(item["case"], item["documents"], k)
        (positive if item["case"]["answerable"] else negative).append(score)
    return {
        "question_count": len(results),
        "answerable_count": len(positive),
        "unanswerable_count": len(negative),
        f"hit@{k}": mean(item["hit"] for item in positive) if positive else None,
        f"precision@{k}": mean(item["precision"] for item in positive) if positive else None,
        f"recall@{k}": mean(item["recall"] for item in positive) if positive else None,
        f"mrr@{k}": mean(item["reciprocal_rank"] for item in positive) if positive else None,
        "unanswerable_false_positive_rate": (
            mean(item["false_positive"] for item in negative) if negative else None
        ),
        "unanswerable_correct_empty_rate": (
            mean(not item["false_positive"] for item in negative) if negative else None
        ),
    }


def document_snapshot(documents):
    return [
        {"doc_id": document_id(doc), "rank": rank,
         "topic": doc.get("metadata", {}).get("topic"),
         "distance": float(doc["distance"]),
         **({"score": float(doc["score"])} if "score" in doc else {})}
        for rank, doc in enumerate(documents, 1)
    ]


def evaluate_case(case, embedding_model, rerank_model, *,
                  config=DEFAULT_RETRIEVAL_CONFIG, connection_factory=None):
    result = run_retrieval(
        case["question"], embedding_model, rerank_model,
        config=config, connection_factory=connection_factory,
    )
    # 排序对照使用相同的距离筛选后候选；策略对照额外应用重排分数阈值。
    return {
        "case": case,
        "candidates": document_snapshot(result.candidates),
        "ranking_vector": document_snapshot(result.vector_documents),
        "ranking_reranked": document_snapshot(result.reranked_documents),
        "runtime_vector": document_snapshot(result.vector_documents),
        "runtime_reranked": document_snapshot(result.documents),
        "timings": result.timings,
    }


def percentile(values, fraction):
    values = sorted(values)
    position = (len(values) - 1) * fraction
    left = int(position)
    right = min(left + 1, len(values) - 1)
    return values[left] + (values[right] - values[left]) * (position - left)


def summarize_results(rows, config=DEFAULT_RETRIEVAL_CONFIG):
    if not rows:
        raise ValueError("没有可汇总的评估结果")
    # 质量指标每题只计一次；重复运行用于测量延迟，不扩大问题样本数。
    first = {}
    for row in rows:
        first.setdefault(row["case"]["id"], row)
    quality_rows = list(first.values())
    paths = ("ranking_vector", "ranking_reranked", "runtime_vector", "runtime_reranked")

    def quality(items):
        metrics = {
            path: calculate_metrics(
                [{"case": row["case"], "documents": row[path]} for row in items],
                config.final_k,
            ) for path in paths
        }
        metrics["candidates"] = calculate_metrics(
            [{"case": row["case"], "documents": row["candidates"]} for row in items],
            config.candidate_k,
        )
        return metrics

    latency = {}
    for key in ("embedding_ms", "database_ms", "distance_filter_ms", "rerank_ms",
                "vector_total_ms", "rerank_total_ms"):
        values = [row["timings"][key] for row in rows]
        latency[key] = {"p50": percentile(values, .5), "p95": percentile(values, .95)}
    changed = sum(
        any(row[path] != first[row["case"]["id"]][path] for path in paths)
        for row in rows
    )
    slices = {}
    for field in ("category", "split"):
        slices[field] = {
            value: quality([row for row in quality_rows if row["case"][field] == value])
            for value in sorted({row["case"][field] for row in quality_rows})
        }
    return {
        "quality": quality(quality_rows), "slices": slices, "latency_ms": latency,
        "measurement_count": len(rows), "ranking_changes_across_repeats": changed,
    }


def print_evaluation_results(results):
    print(json.dumps(calculate_metrics(results), ensure_ascii=False, indent=2))


def evaluation_retrieval_rerank(test_file, embedding_model, rerank_model, *,
                              config=DEFAULT_RETRIEVAL_CONFIG):
    results = []
    for case in load_test_cases(test_file):
        run = run_retrieval(case["question"], embedding_model, rerank_model, config=config)
        results.append({"case": case, "documents": run.documents})
    print(json.dumps(calculate_metrics(results, config.final_k), ensure_ascii=False, indent=2))
    return results


def evaluation_retrieval_without_rerank(test_file, embedding_model, *,
                                      config=DEFAULT_RETRIEVAL_CONFIG):
    results = []
    for case in load_test_cases(test_file):
        run = run_retrieval(case["question"], embedding_model, config=config)
        results.append({"case": case, "documents": run.documents})
    print(json.dumps(calculate_metrics(results, config.final_k), ensure_ascii=False, indent=2))
    return results
