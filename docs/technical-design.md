# 技术设计与实现边界

## 为什么使用异步任务与共享卷

CSV 上传包含数据处理和逐组模型调用，耗时及外部服务响应不可预测。API 将其交给 Celery，由 worker 处理，客户端使用任务 ID 轮询。API 与 worker 运行在不同容器，API 写入共享卷，队列传递文件标识，由 worker 读取相同卷；宿主机与容器混用时也必须保证两端看到同一目录。队列、文件和数据库不是一个原子事务，因此可能出现投递结果不确定或残留暂存文件。

## 幂等与恢复

CSV 与单记录报告分别维护按用户和 UUID 幂等键约束的表；冲突返回原任务信息，重复请求不会正常创建第二个任务。提交前的明确失败可释放键；broker 投递结果不确定时保留键和任务 ID。使用新键重新上传相同文件仍可能创建新记录，系统没有按文件内容全局去重。

Worker 原子认领 `celery_task_states` 的任务租约，heartbeat 刷新期限；数据库写入前检查有效租约，并在同一事务中以条件更新标记 `COMMITTED`。已提交结果可供重投后恢复，减少重复入库。Watchdog 将过期 `RUNNING`/`COMMITTED` 状态重置为 `RETRY` 并保留已提交结果；它不主动重新投递消息，能否继续执行依赖 Celery 的消息重投递。模型调用等外部副作用可能重复，不承诺恰好一次。

## 并发与数据隔离

数据库约束确保上传键与用户组合唯一、飞行器编号唯一，并为任务来源和用户归属提供约束。记录更新基于 `version` 条件写入，版本过期返回 409；写成功后清除缓存，如缓存清除失败则返回 503 并附已更新版本。用户身份由认证上下文提供，worker 从持久任务状态恢复归属，不接受 CSV 指定所有者。

## 检索与重排

向量召回便于从知识库找语义相近的候选；CrossEncoder 逐对评估问题和候选文本，重排可改善排序，但需要额外推理开销，效果必须用具体数据集测量。当前实现按 `metadata.type` 筛选，而不是任意 metadata 字段；`retrieve` 接受 Top-K 与距离阈值参数。`evaluation_retrieval_without_rerank` 和 `evaluation_retrieval_rerank` 分别比较原始召回与重排后的结果：`mean_recall` 是每个问题至少有一个期望主题命中的比例，`mean_precision` 是结果中期望主题比例的均值，`mean_mrr` 是首个命中排名倒数的均值。

## 状态、工具和输出

LangGraph State 记录消息、工具调用、上下文、摘要、摘要游标和最终回答；summary 节点选择较旧完整轮次，agent 决定调用工具或结束，tool 执行后回到 agent。tiktoken 用于上下文选择和工具结果预算，超预算时不能等同于模型处理了完整结果。API 使用 PostgreSQL 检查点管理跨请求状态，并校验会话归属；独立演示可使用内存检查点。

生成飞行报告时，Python 先算统计结果，再请求模型输出 JSON，最后由 Pydantic `FlightReport` 验证字段；助手 API 使用 `AssistantResponse` 定义响应。模型回答不是确定性安全结论。

## 测试策略

基础测试通过 fixture、假连接、假缓存及 monkeypatch 隔离部分数据库和模型调用；TestClient 测试 HTTP 请求和鉴权。`verification/` 有幂等、租约和 checkpoint 等专项用例，也有默认跳过、需显式启用的实库测试。Compose 测试服务使用 `uav_project_test` 和独立 Redis 逻辑库、CSV 卷；这是集成环境隔离，不能说明所有 pytest 都连接真实测试库。Postman 需另行针对实际运行的测试环境验证。并发和故障恢复需要在真实队列及数据库中进一步验证。
