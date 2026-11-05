# 历史学习版本

本目录保存 2026-11-05 整理结构时归档的代码，供阅读、比较和学习。它不是当前应用的依赖，也不作为可运行的业务入口；其中的旧导入路径、数据库表和接口参数按历史原样保留。

## 归档内容

| 原路径 | 内容 | 处理 |
| --- | --- | --- |
| `src/agent/loop/` | 手写循环 Agent、状态和节点 | 移入归档 |
| `src/agent/flight_qa.py` | 旧的两阶段工具问答 | 移入归档 |
| `src/agent/memory/short_term_memory.py` | 手写循环使用的消息容器 | 移入归档 |
| `src/rag/rag.py` | 旧 `UAVAssistant` 检索问答 | 移入归档 |
| `src/agent/tools/get_latest_flight_analysis.py`、`get_flight_analysis_by_id.py` | 旧问答专用工具包装 | 移入归档 |
| `src/database/flight_analysis_repository.py` | 已退役 `flight_analyses` 表的仓储 | 移入归档 |
| `src/cache/flight_analysis_cache.py` | 旧表缓存；通用逻辑已提取到当前 `cache_aside.py` | 移入归档 |
| `examples/postgres_demo.py` | 写入旧表的演示 | 移入归档 |
| `main.py` | 整理前的开发入口和注释实验 | 保留原始快照，当前入口已简化 |
| `src/agent/graph/graph.py` | 含重复 `graph_work()` 的旧构建与演示 | 保留原始快照，当前仅保留 `build_graph()` |
| `tests/test_tools.py` | 旧工具包装的测试 | 保留原始快照，当前测试改为覆盖现行工具 |

共 14 个文件移入归档，另有 3 个文件保留整理前快照。子目录保留原路径，完整文件清单和 SHA-256 见 [manifest.json](manifest.json)。清单可用于核对归档内容是否完整，也可在需要对比历史时定位原文件。

## 当前入口

- 在线问答：`api.py → app/app.py → app/ai_router.py → src/agent/graph/graph.py`。
- 开发演示：`main.py` 或 `examples/agent_demo.py`；两者使用同一 `build_graph()`。
- CSV 报告：`app/tasks.py → src/llm/llm_report.py`，继续保留现有 Celery 业务流程。

当前代码不导入本目录。pytest 默认仅收集 `tests/` 和 `verification/`，且排除归档目录；Docker 构建也排除归档，Git 忽略规则则保留它以便追踪历史。
