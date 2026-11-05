# 当前项目结构与入口

## 目录职责

```text
UAV_project_refactored/
├── api.py                    # Web 服务入口，兼容 uvicorn api:app
├── main.py                   # 开发演示入口，委托给 examples.agent_demo
├── app/                      # FastAPI 生命周期、认证、路由、页面、Celery 任务
├── src/
│   ├── agent/
│   │   ├── graph/            # 当前对话编排，只有 build_graph 一处构建入口
│   │   ├── memory/           # 当前上下文选择和历史摘要
│   │   ├── tools/            # 飞行查询、分析、RAG 工具及注册
│   │   ├── result_processor.py
│   │   └── answer_guard.py
│   ├── cache/
│   │   ├── cache_aside.py    # 通用回源、写缓存和错误处理
│   │   └── flight_record_cache.py
│   ├── database/             # 连接池、当前表仓储、幂等和任务租约
│   ├── flight_data/          # CSV 校验、分组、清洗与统计
│   ├── rag/                  # 分块、向量、检索、重排和评估
│   ├── llm/                  # 客户端、提示词和结构化报告
│   ├── auth/, common/, plot/
│   └── schemas.py
├── examples/                 # 当前可使用的独立演示
├── archive/learning/         # 历史代码与原始快照，不参与业务运行
├── tests/, verification/     # 基础测试和显式启用的验证入口
├── pytest.ini                # 测试收集范围，排除历史归档和临时目录
├── scripts/, sql/            # 初始化、迁移、测试环境维护
└── docs/, data/, reference/, logs/, backups/
```

## 在线问答

`api.py` 导入 `app/app.py` 创建的应用。应用生命周期准备检索模型、Redis、业务连接池和 PostgreSQL 检查点池，再调用 `build_graph()` 创建 Graph。模型通过闭包传给工具节点。

浏览器聊天页和两个兼容问答接口都调用 `app/ai_router.py` 中的 `invoke_user_agent_graph()`，先做登录与会话归属检查，再执行 Graph。Graph 按 `summary → agent → tool → agent` 编排，最后返回回答；旧的循环 Agent 和 `UAVAssistant` 已归档。

## CSV 报告

上传路由负责身份校验、幂等登记、暂存文件和发布 Celery 任务。worker 解析分组、计算统计、逐组生成报告，全部成功后再统一入库。这条现有结构化报告链路继续由 `src/llm/llm_report.py` 承担，不属于本次对话 Graph 整理的修改范围。

## 缓存与仓储

业务缓存仅依赖当前 `flight_record_repository.py`。共享的 `CacheWriteError` 和 `_read_through()` 放在 `src/cache/cache_aside.py`，读缓存失败继续查库，写缓存失败仍向调用方报错。`src/database/__init__.py` 仅保留连接入口，不再导出旧表仓储。

## 开发演示与历史代码

`main.py`、`examples.agent_demo`、`examples.rag_demo` 共用当前 Graph 演示实现。运行时必须显式给出已有用户的 `--user-id`，用于设置飞行数据查询范围；这是开发者命令行入口，Web 入口仍执行 JWT 校验。命令行使用内存检查点，Web 使用 PostgreSQL 检查点。

归档清单见 [历史学习版本](../archive/learning/README.md)。归档保存原始内容，不承诺能在当前数据库和接口上直接运行；没有为它添加新的兼容业务路径。

## 测试和版本追踪

基础测试使用假连接、缓存、Graph 和模型响应。实库验证仍需显式启用，真实服务链路可由 Postman 验证。测试不自动清理日常数据库。

`.gitignore` 排除密钥、虚拟环境、字节码、日志、备份和临时测试目录，保留配置示例、SQL、测试及学习归档。本次未初始化 Git 仓库或推送远程；最终提交位置与分支需另行核对。

## 本次整理验证（2026-11-05）

- `tests/` 全部基础测试与 `verification/test_graph_checkpoint.py`：82 项通过，使用替身，不访问真实数据库或模型。
- 默认测试收集：154 项，仅表示能够收集；本轮未执行全部 154 项。归档、备份和临时测试目录未被收集。
- 17 份归档内容的 SHA-256 校验通过；14 个已移动文件的旧路径已不存在。
- 对比语法树确认 `build_graph()` 的实际构建逻辑、`_read_through()` 的缓存处理逻辑保持一致；当前代码不再引用已归档模块。
- 101 个当前 Python 文件的语法检查通过；根目录入口和兼容 RAG 演示的 `--help` 在没有模型密钥时正常显示。

本轮未调整 RAG 评估、同步原项目、更新容器或执行 Postman 实际服务联调。
