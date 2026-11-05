# 演示与实验代码

项目根目录的 `main.py` 委托给本目录的 `agent_demo.py`，复用当前 `src/agent/graph/graph.py` 中的 `build_graph()`。可复用的业务代码放在 `src/`，历史实现放在 `archive/learning/`。

请在项目根目录运行以下命令。`-m` 表示按模块运行，让演示能够找到项目中的 `src`。

| 文件 | 用途 | 说明 |
| --- | --- | --- |
| `agent_demo.py` | 输入问题，调用当前 Agent graph | 显式传入已有用户的 `--user-id`，使用内存检查点 |
| `rag_demo.py` | 原检索演示模块名的兼容入口 | 委托给 `agent_demo.py`，由 Graph 选择工具 |
| `import_documents.py` | 分块、生成向量并把知识资料写入 `documents` | 按运行环境选择数据库 |
| `llm_demo.py` | 固定数据的独立模型调用实验 | 用于观察模型响应，不代表当前结构化报告接口 |
| `embedding_demo.py` | 比较示例问题和资料的向量相似度 | 仅加载向量模型 |
| `langgraph_lesson1.py`、`langgraph_checkpoint_demo.py` | 独立的 Graph 基础示例 | 不接入 Web 或业务数据库 |

```powershell
.\.venv\Scripts\python.exe main.py --user-id 1 --question "无人机什么时候需要返航？"
.\.venv\Scripts\python.exe -m examples.agent_demo --user-id 1
.\.venv\Scripts\python.exe -m examples.rag_demo --user-id 1
.\.venv\Scripts\python.exe -m examples.import_documents
.\.venv\Scripts\python.exe -m examples.llm_demo
.\.venv\Scripts\python.exe -m examples.embedding_demo
```

以上 `1` 是示例用户编号，需替换为当前数据库中已有用户 ID。命令行入口供开发者使用，不经过 Web 登录；浏览器与问答 API 仍要求 JWT 和会话归属校验。

这些命令分别运行不同的演示，按需要选择一条。重复运行资料导入会重复插入资料；Agent 和独立模型演示会向模型服务发送请求，向量和检索演示会加载相应模型。在 Windows 上访问容器数据库仍需要自行配置宿主机可达地址，当前 Compose 没有发布数据库端口。

旧的 `postgres_demo.py` 写入已退役表，现已归档，不再提供运行命令。历史位置和原始内容校验见 [归档说明](../archive/learning/README.md)。完整调用关系见 [项目结构说明](../docs/project_structure.md)。
