from src.agent.graph.graph import build_graph
from src.rag.model_factory import create_retrieval_models


def main():
    models = create_retrieval_models()
    graph = build_graph(
        rerank_model=models["rerank_model"],
        embedding_model=models["embedding_model"],
        checkpointing=False,
    )
    question = input("question: ")
    initial_state = {
        "query": question,
        "context": [],
        "message": [{"role": "user", "content": question}],
        "current_tool_call": None,
        "tool_results": [],
        "conversation_summary": "",
        "summary_cursor": 0,
        "answer": "",
        "finished": False,
    }
    result = graph.invoke(initial_state)
    print(f"Answer: {result['answer']}")


if __name__ == "__main__":
    main()
