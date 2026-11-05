# 开发者命令行演示复用线上 Graph 构建函数，不自行定义另一套节点和边。
import argparse
from uuid import uuid4

from src.auth.data_scope import use_data_user


def run_question(question: str, user_id: int) -> dict:
    # 延迟导入，查看命令帮助时无需模型密钥，也不会加载检索模型。
    from src.agent.graph.graph import build_graph
    from src.rag.model_factory import create_retrieval_models

    models = create_retrieval_models()
    graph = build_graph(
        embedding_model=models["embedding_model"],
        rerank_model=models["rerank_model"],
    )
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
    # 演示使用临时内存检查点；用户编号供开发者指定飞行数据的查询范围。
    config = {"configurable": {"thread_id": str(uuid4())}}
    with use_data_user(user_id):
        return graph.invoke(initial_state, config=config)


def main(argv=None):
    parser = argparse.ArgumentParser(description="使用当前 Agent graph 进行开发演示")
    parser.add_argument("--user-id", type=int, required=True, help="数据库中已有用户的正整数 ID")
    parser.add_argument("--question", help="本次问题；省略时在终端输入")
    args = parser.parse_args(argv)
    if args.user_id <= 0:
        parser.error("--user-id 必须是正整数")
    question = args.question if args.question is not None else input("请输入问题：")
    question = question.strip()
    if not question:
        parser.error("请输入问题")
    result = run_question(question, args.user_id)
    print(result["answer"]["answer"])


if __name__ == "__main__":
    main()
