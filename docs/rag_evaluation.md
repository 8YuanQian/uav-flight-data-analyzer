# RAG 第一轮评估

## 本轮边界

运行入口 `src/agent/tools/rag_search.py` 和评估入口共用 `src/rag/pipeline.py`，
参数集中在 `src/rag/config.py`。默认候选数 10、余弦距离严格小于 0.5、最终最多 3 个片段、
重排分数严格大于 0.77。0.77 是当前模型的分数阈值，不是正确概率。

保留 `intfloat/multilingual-e5-base`、`BAAI/bge-reranker-base` 和原有无前缀编码。
本轮没有增加 `query:` / `passage:`，没有修改日常知识库向量，也不调用付费 LLM。
首版沿用运行参数建立基线，不根据测试集挑选更好看的参数。

## 问题与标注

`data/rag_test_cases.json` 包含 60 题：10 个常规问题、20 个改写问题、15 个易混淆问题、15 个无答案问题。
原来的 6 题仍保留。无答案问题包含未提供的型号精确参数、私有设备记录、实时信息和非无人机话题。
通用注意事项不能当作这些问题的精确答案。

每题提供 `id`、`question`、`category`、`group_id`、`split`、`answerable` 和 `relevant_doc_ids`；
易混淆问题还列出干扰片段。标注按来源和片段原文的 SHA256 识别，不依赖数据库自增 ID 或 topic。
同一意图及其改写必须放在同一 split，避免调参集与测试集互相泄漏。

冻结语料为 `data/uav_rag_knowledge_base_200.json`，沿用 500 字符、50 字符重叠的切片方式。
`data/rag_eval_manifest.json` 保存语料和问题集指纹，以及片段编号与问题的对照。
修改语料或题目后必须重新审查标注并更新清单；评估入口会拒绝指纹不一致的输入。

这是一份按阅读现有资料形成的初始标注，尚未经第二位人工独立复核，也没有穷尽所有可能相关的片段。
因此 Recall 只对已标注的相关片段有效，不能声称已覆盖所有无人机知识或具备专业飞行安全认证。

## 指标与对照

同一次检索产生相同候选池，避免向量对照与重排对照命中不同的候选。候选池已经过距离阈值筛选。

| 结果键 | 含义 |
|---|---|
| `candidates` | 距离筛选后的最多 10 个候选 |
| `ranking_vector` | 候选按向量距离取前 3 个 |
| `ranking_reranked` | 相同候选重排后取前 3 个，不应用重排分数阈值 |
| `runtime_vector` | 不启用重排的运行策略，当前与向量排序对照相同 |
| `runtime_reranked` | 重排后再应用 0.77 阈值，和运行工具一致 |

可回答问题计算 Hit@K、Precision@K、Recall@K、MRR@K。Hit 看是否命中至少一个已标注相关片段；
Precision 看前 K 个位置中有多少标注相关片段，少于 K 个结果时空位也计入分母；
Recall 看已标注相关片段找回多少；MRR 看第一个正确片段的位置。候选阶段另计算 Recall@10。
无答案问题单独计算误召回率和正确空返回率，不进入上述指标的分母。
某一分组没有相应问题时，指标为 `null`，不以 0 冒充有测量结果。

重排排序对照用于观察排名变化；实际策略对照同时反映重排和分数过滤的影响，不能混为一谈。
这里衡量的是检索，不是最终 LLM 回答的正确率或拒答率。

## 运行

先校验问题集，这一步不加载模型或连接数据库：

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_rag.py --validate-only
.\.venv\Scripts\python.exe -m pytest tests/test_rag_evaluation.py -q
```

本机使用已有的 E 盘模型缓存，启动独立的短期评估容器：

```powershell
docker compose -f compose.yaml -f compose.test.yaml -f compose.local.yaml -f compose.test.local.yaml run --rm --no-deps -v "./src:/app/src:ro" -v "./scripts:/app/scripts:ro" -v "./data:/app/data:ro" -v "./evaluation_results:/app/evaluation_results" api-test python scripts/evaluate_rag.py --repeats 3 --warmup 1 --threads 2
```

先在项目根目录准备 `evaluation_results` 文件夹。新环境未使用 local 配置时，可去掉两个 local 文件参数；
需要先启动 PostgreSQL 并准备好模型缓存，评估容器不自动下载模型。

默认 `--corpus-mode temporary` 只允许连接 `uav_project_test`，在连接会话内建立临时 documents 表，
用原有无前缀编码生成评估向量。临时表在连接关闭时移除，不清表、不提交业务数据，持久 documents 不受影响。
测试库已有业务知识文档也不会被覆盖。

可选 `--corpus-mode database` 直接评估现有 documents，连接强制只读且使用可重复读快照；
必须与冻结语料的片段集合完全一致。主机、端口、库名和密码沿用现有数据库环境变量，不在报告中保存密码。
本机数据库不发布端口，优先按上述方式在 Compose 网络内执行。

## E5 前缀对照

使用上面的 Compose 命令，以相同参数分别运行 `--encoding legacy-unprefixed` 和
`--encoding e5-prefixed`。第二组用 `query: ` 编码问题，用 `passage: ` 在 `uav_project_test`
会话临时表批量重建文档向量。正文、片段标识和 BGE 输入仍使用原文。
前缀评估只支持临时表模式，避免将新查询向量与正式知识库旧向量混用。

先对比 `quality.candidates` 的 Recall@10，再看 `quality.runtime_reranked` 的
Precision@3、Recall@3、MRR@3 和无答案误召回率。在固定问题集与固定阈值下比较，
如需调阈值或候选数量，单独记录并在 dev 上选择，最后用 test 验证。

2026-11-20 实测使用同一冻结语料的 200 个片段、60 道题（45 道可回答、15 道无答案）。
两组使用同版本 E5 与 BGE，CPU 2 线程，分别预热 1 次、正式评测 1 轮。
候选上限为 10，最终上限为 3，距离阈值与重排阈值分别为 0.5 和 0.77。

| 指标 | 无前缀 | `query:` / `passage:` |
|---|---:|---:|
| 候选 Recall@10 | 96.67% | 95.56% |
| 重排并应用阈值后的 Precision@3 | 31.11% | 31.11% |
| 重排并应用阈值后的 Recall@3 | 83.33% | 83.33% |
| 重排并应用阈值后的 MRR@3 | 0.8407 | 0.8407 |
| 无答案题收到资料 | 1/15 | 1/15 |

逐题核对后，60 道题的候选列表顺序或成员都有变化，应用重排阈值后的文档 ID 与顺序逐题一致。
候选召回率下降来自 dev 题 `return-2`，该题的两个标注片段在无前缀时都能召回，加前缀后只留一个在候选集。
在当前配置下，保留无前缀作为应用默认编码。前缀方式可通过评估命令复测，测试期间只重建会话临时向量。

实测记录：[无前缀](../evaluation_results/rag/20261120T064952_168344Z/summary.json)、
[有前缀](../evaluation_results/rag/20261120T065128_779507Z/summary.json)。

后续调参可使用 `--split dev --candidate-k 20 --final-k 3 --max-distance 0.5 --min-score 0.77`；
确定参数后再用 `--split test` 做最终检查。第一轮的 all 结果是未调参的基线，不能据此反复挑参数。

## 结果保存与解读

每轮写入 `evaluation_results/rag/<UTC实验编号>/`：

- `config.json`：配置、代码指纹、问题与语料指纹、模型版本、CPU 线程数、模型加载时间、实验状态。
- `per_query.jsonl`：每题每次的候选编号、顺序、距离、重排分数和分阶段耗时。
- `summary.json`：整体、类别及 split 指标；各阶段 P50/P95；重复运行时排名是否变化。
- `comparison.md`：排序与实际策略对照，以及延迟表。

默认 CPU、2 个计算线程，模型只加载一次，预热一次，正式重复三次。模型加载、临时语料向量生成均不计入查询延迟。
向量总耗时包括查询编码、数据库访问和筛选；重排总耗时在同次检索耗时上增加重排处理。
这是配对测量，不是分别向 API 发出两轮请求，也不包含认证、网络请求、Agent、LLM 或队列耗时。
质量每题只计算一次，延迟使用所有重复测量，避免把 60 个问题写成 180 个独立样本。

报告会记录 dev/test 和问题类别的分项结果。分析失败问题时可用片段编号对照清单：
候选阶段未找到是检索或距离筛选问题；候选已有但前三条没有是排序问题；排序命中但实际策略为空则是分数阈值问题。
无答案误召回不代表最终模型一定胡答，但说明当前检索门槛不能直接作为“可回答”的充分条件。

实验遇到异常保留已完成的逐题记录，`config.json` 标为 failed，不生成成功结论。
当前改动不会自动重建或重启正式、测试 API；部署更新另行执行。
