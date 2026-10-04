from src.load_data import load_csv_data,load_data_json_data
from src.rag import retrieve
from src.reranker import rerank_documents


def evaluation_retrieval_rerank(test_file):
    recall = False
    total_recall = 0
    total_precision = 0
    total_mrr = 0
    results = []
    data = load_data_json_data(test_file)
    for i in data:
        question = i['question']
        retrieved_information = retrieve(question,threshold=0.15)
        reranked_information = rerank_documents(question, retrieved_information, top_k=10)
        results.append((question, i["topic"], reranked_information))

    for question, expected_topic, reranked_information in results:
        precision = 0
        mrr = None
        print(f"Question: {question}")
        for index, item in enumerate(reranked_information):
            if item ["metadata"]["topic"] == expected_topic:
                recall = True
                precision += 1
                if mrr is None:
                    mrr = index + 1
            print(f"{index + 1}. Content: {item['content']}, Reranked Score: {item['score']}, Instance: {item['distance']}")
      
        if recall:
            total_recall += 1
            recall = False

        if mrr is None:
            pass
        else:
            total_mrr += 1 / mrr

        if reranked_information:
            total_precision += precision / len(reranked_information)
        else:
            total_precision += 0
        print("\n")

    mean_recall = total_recall / len((data))
    mean_precision = total_precision / len(data)
    mean_mrr = total_mrr / len(data)
    print(f"Mean Recall: {mean_recall}")
    print(f"Mean Precision: {mean_precision}")
    print(f"Mean MRR: {mean_mrr}")
        
    return results

def evaluation_retrieval_without_rerank(test_file):
    results = []
    recall = False
    total_recall = 0
    total_precision = 0
    total_mrr = 0
    results = []
    data = load_data_json_data(test_file)
    for i in data:
        question = i['question']
        retrieved_information = retrieve(question,threshold=0.15)
        results.append((question, i["topic"], retrieved_information))

    for question, expected_topic, retrieved_information in results:
        precision = 0
        mrr = None
        print(f"Question: {question}")
        for index, item in enumerate(retrieved_information):
            if item ["metadata"]["topic"] == expected_topic:
                recall = True
                precision += 1
                if mrr is None:
                    mrr = index + 1
            print(f"{index + 1}. Content: {item['content']}, Instance: {item['distance']}")
      
        if recall:
            total_recall += 1
            recall = False

        if mrr is None:
            pass
        else:
            total_mrr += 1 / mrr

        if retrieved_information:
            total_precision += precision / len(retrieved_information)
        else:
            total_precision += 0
        print("\n")

    mean_recall = total_recall / len((data))
    mean_precision = total_precision / len(data)
    mean_mrr = total_mrr / len(data)
    print(f"Mean Recall: {mean_recall}")
    print(f"Mean Precision: {mean_precision}")
    print(f"Mean MRR: {mean_mrr}")
        
    return results
