from src.flight_data.load_data import load_json_data
from src.rag.retrieve import retrieve
from src.rag.reranker import rerank_documents


def calculate_metrics(results):
    """计算主题命中率、平均准确率和平均倒数排名。

    results 中的每项是 (问题, 期望主题, 检索资料列表)。
    mean_recall 沿用原来的定义：至少命中一次期望主题的问题占比。
    """
    if not results:
        return {"mean_recall": 0.0, "mean_precision": 0.0, "mean_mrr": 0.0}

    hit_count = 0
    total_precision = 0.0
    total_reciprocal_rank = 0.0

    for question, expected_topic, documents in results:
        matching_count = 0
        first_match_rank = None

        for rank, document in enumerate(documents, start=1):
            if document["metadata"]["topic"] == expected_topic:
                matching_count += 1
                if first_match_rank is None:
                    first_match_rank = rank

        if matching_count > 0:
            hit_count += 1
        if documents:
            total_precision += matching_count / len(documents)
        if first_match_rank is not None:
            total_reciprocal_rank += 1 / first_match_rank

    question_count = len(results)
    return {
        "mean_recall": hit_count / question_count,
        "mean_precision": total_precision / question_count,
        "mean_mrr": total_reciprocal_rank / question_count,
    }


def print_evaluation_results(results):
    """显示每个问题的检索结果和整体评估指标。"""
    if not results:
        print("没有评估用例")

    for question, expected_topic, documents in results:
        print(f"Question: {question}")
        for rank, document in enumerate(documents, start=1):
            if "score" in document:
                print(
                    f"{rank}. Content: {document['content']}, "
                    f"Reranked Score: {document['score']}, "
                    f"Distance: {document['distance']}"
                )
            else:
                print(
                    f"{rank}. Content: {document['content']}, "
                    f"Distance: {document['distance']}"
                )
        print()

    metrics = calculate_metrics(results)
    print(f"Mean Recall: {metrics['mean_recall']}")
    print(f"Mean Precision: {metrics['mean_precision']}")
    print(f"Mean MRR: {metrics['mean_mrr']}")


def evaluation_retrieval_rerank(test_file, embedding_model, rerank_model):
    test_cases = load_json_data(test_file)
    results = []
    for test_case in test_cases:
        question = test_case["question"]
        documents = retrieve(question, embedding_model, threshold=0.15)
        reranked_documents = rerank_documents(question, documents, rerank_model, top_k=10)
        results.append((question, test_case["topic"], reranked_documents))

    print_evaluation_results(results)
    return results


def evaluation_retrieval_without_rerank(test_file, embedding_model):
    test_cases = load_json_data(test_file)
    results = []
    for test_case in test_cases:
        question = test_case["question"]
        documents = retrieve(question, embedding_model, threshold=0.15)
        results.append((question, test_case["topic"], documents))

    print_evaluation_results(results)
    return results
