# 基础测试只用假模型和假连接，不联网、不清表、不加载真实模型。
from copy import deepcopy
from dataclasses import FrozenInstanceError
from importlib import import_module
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.rag.config import DEFAULT_RETRIEVAL_CONFIG, RetrievalConfig
from src.rag.document_identity import document_id
from src.rag.embedding import E5_ENCODING
from src.rag.evaluation import calculate_metrics, load_test_cases, summarize_results
from src.rag import pipeline
from src.rag.reranker import rerank_documents


def doc(content, distance=.1):
    return {"content": content, "source": "test", "metadata": {"topic": "相同主题"},
            "distance": distance}


def case(relevant, *, answerable=True, number="test-1"):
    return {"id": number, "question": "测试问题", "category": "normal",
            "group_id": number, "split": "dev", "answerable": answerable,
            "relevant_doc_ids": [document_id(item) for item in relevant]}


def test_metrics_use_document_labels_and_separate_unanswerable():
    correct, other, second = doc("正确资料"), doc("相同主题的错误资料"), doc("另一正确资料")
    metrics = calculate_metrics([
        {"case": case([correct, second]), "documents": [other, correct]},
        {"case": case([], answerable=False, number="no-1"), "documents": [other]},
        {"case": case([], answerable=False, number="no-2"), "documents": []},
    ])
    assert metrics["answerable_count"] == 1
    assert metrics["unanswerable_count"] == 2
    assert metrics["hit@3"] == 1
    assert metrics["precision@3"] == pytest.approx(1 / 3)
    assert metrics["recall@3"] == .5
    assert metrics["mrr@3"] == .5
    assert metrics["unanswerable_false_positive_rate"] == .5


def test_same_topic_does_not_mean_correct_and_duplicate_hits_do_not_inflate_recall():
    correct, wrong = doc("正确"), doc("错误")
    assert calculate_metrics([{"case": case([correct]), "documents": [wrong]}])["hit@3"] == 0
    assert calculate_metrics([{"case": case([correct]), "documents": [correct, correct]}])["recall@3"] == 1


def test_empty_results_have_explicit_counts_and_no_fake_zero_denominator():
    assert calculate_metrics([])["hit@3"] is None
    assert calculate_metrics([])["unanswerable_false_positive_rate"] is None
    assert calculate_metrics([{"case": case([doc("正确")]), "documents": []}])["hit@3"] == 0


def test_config_preserves_runtime_baseline_and_is_immutable():
    assert DEFAULT_RETRIEVAL_CONFIG == RetrievalConfig(10, .5, 3, .77)
    with pytest.raises(FrozenInstanceError):
        DEFAULT_RETRIEVAL_CONFIG.final_k = 10


@pytest.mark.parametrize("changes", [
    {"candidate_k": 0}, {"final_k": True}, {"final_k": 11},
    {"max_cosine_distance": 3}, {"min_rerank_score": float("nan")},
])
def test_invalid_config_is_rejected(changes):
    with pytest.raises(ValueError):
        RetrievalConfig(**changes)


def test_shared_pipeline_scores_same_candidates_once_and_separates_score_gate(monkeypatch):
    documents = [doc("第一"), doc("第二"), doc("第三"), doc("第四")]
    before = deepcopy(documents)
    retrieve = MagicMock(return_value=documents)
    monkeypatch.setattr(pipeline, "retrieve", retrieve)
    model = MagicMock()
    model.predict.return_value = [.2, .77, .9, .8]

    result = pipeline.run_retrieval("问题", object(), model)

    assert result.vector_documents == documents[:3]
    assert [item["content"] for item in result.reranked_documents] == ["第三", "第四", "第二"]
    assert [item["content"] for item in result.documents] == ["第三", "第四"]
    assert model.predict.call_count == 1
    assert model.predict.call_args.args[0] == [("问题", item["content"]) for item in documents]
    assert retrieve.call_args.kwargs["top_k"] == DEFAULT_RETRIEVAL_CONFIG.candidate_k
    assert retrieve.call_args.kwargs["threshold"] == DEFAULT_RETRIEVAL_CONFIG.max_cosine_distance
    assert documents == before


def test_empty_candidates_do_not_call_reranker(monkeypatch):
    monkeypatch.setattr(pipeline, "retrieve", lambda *args, **kwargs: [])
    model = MagicMock()
    assert pipeline.run_retrieval("无答案", object(), model).documents == []
    model.predict.assert_not_called()


def test_reranker_detects_missing_scores():
    model = MagicMock()
    model.predict.return_value = []
    with pytest.raises(ValueError, match="数量"):
        rerank_documents("问题", [doc("资料")], model)


def test_runtime_tool_delegates_to_shared_config_without_exposing_diagnostics(monkeypatch):
    tool = import_module("src.agent.tools.rag_search")
    run = MagicMock()
    run.documents = [doc("公开资料")]
    execute = MagicMock(return_value=run)
    monkeypatch.setattr(tool, "run_retrieval", execute)
    embedding, reranker = object(), object()
    assert tool.rag_search("问题", embedding_model=embedding, rerank_model=reranker) == run.documents
    assert execute.call_args.kwargs["config"] is DEFAULT_RETRIEVAL_CONFIG


def test_frozen_dataset_has_60_cases_and_keeps_original_six_questions():
    root = Path(__file__).resolve().parents[1]
    cases = load_test_cases(root / "data/rag_test_cases.json",
                            root / "data/uav_rag_knowledge_base_200.json")
    assert len(cases) == 60
    assert sum(item["category"] == "paraphrase" for item in cases) == 20
    assert sum(item["category"] == "confusing" for item in cases) == 15
    assert sum(not item["answerable"] for item in cases) == 15
    assert {"无人机什么时候自动返航？", "无人机电池低于多少需要返航？", "GPS丢失怎么办？",
            "无人机在飞行中遇到强风怎么办？", "飞控系统出现故障时应该如何处理？",
            "飞行过程中GPS信号丢失，应该如何应对？"} <= {item["question"] for item in cases}


@pytest.mark.parametrize("mutation", ["unknown_document", "split_leakage", "bad_answerability"])
def test_bad_annotations_are_rejected(tmp_path, mutation):
    correct = doc("原文")
    items = [case([correct])]
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps([correct]), encoding="utf-8")
    if mutation == "unknown_document":
        items[0]["relevant_doc_ids"] = ["unknown"]
    elif mutation == "split_leakage":
        items.append({**items[0], "id": "test-2", "split": "test"})
    else:
        items[0]["answerable"] = False
    dataset = tmp_path / "cases.json"
    dataset.write_text(json.dumps(items), encoding="utf-8")
    with pytest.raises(ValueError):
        load_test_cases(dataset, corpus)


def test_repeats_only_increase_latency_measurements_not_quality_sample_size():
    correct = doc("正确")
    row = {"case": case([correct]), "candidates": [correct],
           "timings": {key: 10 for key in ("embedding_ms", "database_ms", "distance_filter_ms",
                                           "rerank_ms", "vector_total_ms", "rerank_total_ms")}}
    for path in ("ranking_vector", "ranking_reranked", "runtime_vector", "runtime_reranked"):
        row[path] = [correct]
    summary = summarize_results([row, deepcopy(row), deepcopy(row)])
    assert summary["measurement_count"] == 3
    assert summary["quality"]["runtime_reranked"]["question_count"] == 1
    assert summary["latency_ms"]["rerank_total_ms"] == {"p50": 10, "p95": 10}


def test_retrieve_keeps_legacy_query_encoding_and_strict_distance_boundary():
    module = import_module("src.rag.retrieve")
    embedding = MagicMock()
    embedding.encode.return_value.tolist.return_value = [1, 2]
    connection = MagicMock()
    cursor = connection.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [
        ("有效", "test", {}, .49), ("边界", "test", {}, .5), ("空向量", "test", {}, None),
    ]
    timings = {}
    result = module.retrieve("原始查询", embedding, connection_factory=lambda: connection, timings=timings)
    embedding.encode.assert_called_once_with("原始查询")
    assert [item["content"] for item in result] == ["有效"]
    assert timings["raw_candidate_count"] == 3
    assert cursor.execute.call_args.args[1] == ([1, 2], 10)


def test_e5_prefix_changes_embedding_input_but_not_reranker_text():
    embedding = MagicMock()
    embedding.encode.return_value.tolist.return_value = [1, 2]
    reranker = MagicMock()
    reranker.predict.return_value = [.9]
    connection = MagicMock()
    cursor = connection.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [("文档原文", "test", {}, .12)]

    result = pipeline.run_retrieval(
        "用户问题", embedding, reranker, config=RetrievalConfig(encoding=E5_ENCODING),
        connection_factory=lambda: connection,
    )

    embedding.encode.assert_called_once_with("query: 用户问题")
    reranker.predict.assert_called_once_with([("用户问题", "文档原文")])
    assert [item["content"] for item in result.documents] == ["文档原文"]


def test_e5_temporary_corpus_passage_prefix_preserves_stored_text(monkeypatch):
    from scripts import evaluate_rag
    from src.database import connection as database

    connect = MagicMock()
    cursor = connect.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = ("uav_project_test",)
    cursor.fetchall.return_value = [("资料", "test")]
    monkeypatch.setattr(database, "get_connection", lambda: connect)
    model = MagicMock()
    vector = MagicMock()
    vector.tolist.return_value = [1, 2]
    model.encode.return_value = [vector]

    with evaluate_rag.evaluation_connection("temporary", [doc("资料")], model, encoding=E5_ENCODING):
        model.encode.assert_called_once_with(["passage: 资料"], batch_size=8, show_progress_bar=False)
        assert cursor.executemany.call_args.args[1][0][0] == "资料"

    with pytest.raises(ValueError, match="temporary"):
        with evaluate_rag.evaluation_connection("database", [doc("资料")], model, encoding=E5_ENCODING):
            pytest.fail("前缀评估不能复用持久表里的旧向量")


def test_e5_document_upload_prefixes_only_embedding_input(monkeypatch):
    from src.rag import document_save_to_database as writer

    model = MagicMock()
    model.encode.return_value.tolist.return_value = [1, 2]
    save = MagicMock()
    monkeypatch.setattr(writer, "save_document", save)

    writer.save_document_to_database([doc("资料原文")], model, "documents", encoding=E5_ENCODING)

    model.encode.assert_called_once_with("passage: 资料原文")
    assert save.call_count == 1
    assert save.call_args.args[0] == "资料原文"
    assert save.call_args.args[3:] == ([1, 2], "documents")


def test_evaluation_container_can_run_without_git(monkeypatch):
    from scripts import evaluate_rag

    def missing_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(evaluate_rag.subprocess, "run", missing_git)
    assert evaluate_rag.git_commit() is None


def test_temporary_corpus_refuses_non_test_database(monkeypatch):
    from scripts import evaluate_rag
    from src.database import connection as database

    connect = MagicMock()
    cursor = connect.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = ("uav_project",)
    monkeypatch.setattr(database, "get_connection", lambda: connect)
    model = MagicMock()
    with pytest.raises(ValueError, match="只允许连接"):
        with evaluate_rag.evaluation_connection("temporary", [doc("资料")], model):
            pytest.fail("不应允许连接日常库")
    model.encode.assert_not_called()
    assert len(cursor.execute.call_args_list) == 1
