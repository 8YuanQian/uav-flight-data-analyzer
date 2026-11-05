# 初始化模型和分词器缓存；只准备本地资源，不调用付费 LLM。
import gc
import os
from pathlib import Path
import subprocess
import sys


def load_resources():
    import tiktoken
    from sentence_transformers import CrossEncoder, SentenceTransformer

    tiktoken.get_encoding("o200k_base")
    # 依次释放模型，避免初始化时同时占用两份模型内存。
    embedding = SentenceTransformer("intfloat/multilingual-e5-base")
    del embedding
    gc.collect()
    reranker = CrossEncoder("BAAI/bge-reranker-base")
    del reranker
    gc.collect()


def main():
    if "--offline-check" in sys.argv:
        load_resources()
        return
    # 缓存完整时优先离线检查；缓存缺失或损坏时再联网补齐。
    environment = dict(os.environ, HF_HUB_OFFLINE="1")
    command = [sys.executable, str(Path(__file__).resolve()), "--offline-check"]
    result = subprocess.run(command, env=environment, capture_output=True, text=True)
    if result.returncode == 0:
        print("模型和分词器缓存检查完成，无需重新下载。", flush=True)
        return
    print("本地资源不完整，开始准备模型和分词器缓存。", flush=True)
    os.environ["HF_HUB_OFFLINE"] = "0"
    load_resources()
    # 最后按 API 的离线配置再检查一次；失败会让初始化容器非零退出。
    subprocess.run(command, env=environment, check=True)
    print("资源准备完成，可以离线启动 API 和 worker。", flush=True)


if __name__ == "__main__":
    main()
