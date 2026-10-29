# 演示与实验代码

项目根目录的 `main.py` 是 LangGraph Agent 演示入口；可复用的业务代码放在 `src/`；独立演示放在这里。

请在项目根目录运行以下命令。`-m` 表示按模块运行，让演示能够找到项目中的 `src`。

| 文件 | 用途 | 原位置 |
| --- | --- | --- |
| `rag_demo.py` | 输入问题，运行检索问答 | `main.py` 中注释掉的问答代码 |
| `import_documents.py` | 分块、生成向量并把知识资料写入数据库 | `main.py` 中注释掉的资料导入代码 |
| `llm_demo.py` | 根据固定的示例数据调用模型生成报告 | `llm_test.py` |
| `postgres_demo.py` | 向 `uav_project` 数据库写入一条示例分析记录 | `PostgreSQL.py` |
| `embedding_demo.py` | 比较示例问题和资料的向量相似度 | `src/embedding_test.py` |

```powershell
.\.venv\Scripts\python.exe main.py
.\.venv\Scripts\python.exe -m examples.rag_demo
.\.venv\Scripts\python.exe -m examples.import_documents
.\.venv\Scripts\python.exe -m examples.llm_demo
.\.venv\Scripts\python.exe -m examples.postgres_demo
.\.venv\Scripts\python.exe -m examples.embedding_demo
```

这些命令分别运行不同的演示，按需要选择一条。数据库演示会写入数据；重复运行资料导入会重复插入资料。模型报告演示会向模型服务发送请求，向量和检索演示会加载相应模型。

正式的飞行问答逻辑已经从 `tools_calling_demo.py` 移至 `src/agent/flight_qa.py`，由 `api.py` 调用。
