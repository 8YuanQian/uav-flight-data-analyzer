from src.evaluation import evaluation_retrieval_rerank,evaluation_retrieval_without_rerank
from src.rag import UAVAssistant


def main():
    # print("===========retrieval===========")
    # evaluation_retrieval_without_rerank("rag_test_cases.json")
    # print()
    # print("===========retrieval + rerank===========")
    # evaluation_retrieval_rerank("rag_test_cases.json")
    
    query = input("question: ")
    print(UAVAssistant().ask(query)["content"])


if __name__ == "__main__":
    main()
