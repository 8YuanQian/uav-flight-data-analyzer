# 无人机飞行数据分析项目

这个项目包含三个部分：

- 读取飞行 CSV，清洗数据、计算统计信息，并调用模型生成分析报告。
- 将分析记录保存在 PostgreSQL 中，通过接口或自然语言问题查询记录。
- 从无人机知识资料中检索相关内容，重新排序后回答问题，并比较检索效果。

## 文件放在哪里

```text
UAV_project/
├── api.py                     # FastAPI 接口入口
├── main.py                    # 检索效果评估入口
├── src/                       # 可复用的业务代码
│   ├── load_data.py            # 读取 CSV 和 JSON
│   ├── clean_data.py           # 清洗飞行数据
│   ├── analyze_data.py         # 计算统计信息
│   ├── database.py             # 连接数据库，保存和查询分析记录
│   ├── model.py                # 请求和报告的数据模型
│   ├── flight_qa.py            # 飞行记录问答和工具调用
│   ├── document_save_to_database.py  # 资料分块、生成向量并入库
│   ├── retrieve.py             # 从数据库检索知识资料
│   ├── reranker.py             # 对检索结果重新排序
│   ├── rag.py                  # 组合检索、提示词和模型回答
│   └── evaluation.py           # 检索评估和共同的指标计算
├── tools/                     # 模型可以调用的飞行记录查询工具
├── examples/                  # 独立演示，见 examples/README.md
├── tests/                     # 接口和工具测试
├── data/                      # 飞行数据、知识资料和评估用例
├── reference/                 # 参考资料
├── backups/                   # 整理代码前的备份
├── PostgreSQL.sql             # 飞行记录建表语句和 SQL 练习
├── requirements.txt           # 运行依赖
└── requirements-dev.txt       # 运行依赖及测试依赖
```

`flight_qa` 中的 `flight` 指飞行，`qa` 是 Question Answering（问答）的缩写。这份文件负责根据问题选择查询工具，再用查询结果生成回答。

## 准备 Python 环境

使用 Python 3.11，在项目根目录打开 PowerShell。已有 `.venv` 时保留它；没有时再创建：

```powershell
if (-not (Test-Path .venv)) {
    uv venv --python 3.11 .venv
}
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
```

依赖版本主要来自整理时项目环境中已安装的版本，并补上启动接口、接收上传文件所需的包。这是直接依赖清单；安装命令仍需要在你的环境中执行。下面的运行命令直接使用项目解释器，不需要先激活环境。

## 设置环境变量

代码通过 `os.getenv()` 读取配置。请在运行程序的同一个 PowerShell 窗口设置变量：

```powershell
$env:DEEPSEEK_API_KEY = "填入你的模型 API 密钥"
$env:PASSWORD = "填入你的 PostgreSQL 密码"
$env:UAV_DB_NAME = "uav_project"
$env:PORT = "5432"
```

| 变量 | 用途 | 当前默认值 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | 模型服务密钥；接口启动时也会检查它 | 无 |
| `PASSWORD` | PostgreSQL 密码 | 无 |
| `UAV_DB_NAME` | 数据库名称 | `uav_project` |
| `PORT` | PostgreSQL 端口 | `5432` |

数据库主机和用户目前在 `src/database.py` 中固定为 `localhost`、`postgres`。项目没有自动加载 `.env` 的代码，因此只创建 `.env` 文件不会使配置生效。密钥和密码不要写进代码或提交到仓库。

## 准备数据库

飞行记录功能需要 PostgreSQL 中的 `flight_analyses` 表。建表语句在 `PostgreSQL.sql` 中；这个文件也包含插入、更新和删除的练习语句，初始化时只选择需要的建表部分。

知识检索还需要 pgvector 扩展，以及 `documents` 表中的 `content`、`source`、`metadata`、`embedding` 字段。`metadata` 保存 JSON 对象，`embedding` 保存向量，其维度需要与所用模型的输出一致。当前 `PostgreSQL.sql` 尚未提供这张表的建表语句，运行资料导入和检索前需要准备好这张表。

## 启动接口

```powershell
.\.venv\Scripts\python.exe -m uvicorn api:app --reload
```

启动后打开 [接口文档](http://127.0.0.1:8000/docs)。主要接口如下：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/health` | 检查服务状态 |
| GET | `/analysis/summary` | 统计 `data/data.csv` 中的示例数据 |
| POST | `/flights/validate` | 校验一条飞行记录 |
| POST | `/flights/analyze` | 上传 CSV，保存统计结果并生成模型报告 |
| GET | `/flights/{analysis_id}` | 根据编号查询分析记录 |
| GET | `/flights?limit=5` | 查询最近的记录，数量范围为 1～100 |
| POST | `/flights/model` | 根据问题查询飞行分析记录并生成回答 |

上传 CSV 至少需要 `time`、`speed`、`height`、`battery`、`temperature` 五列。问答接口的请求体示例：

```json
{"question": "最近一次飞行的最高速度是多少？"}
```

## 运行知识问答和检索评估

先准备知识数据库，按需要运行以下命令：

```powershell
# 导入 data/uav_knowledge.json，会向数据库写入资料
.\.venv\Scripts\python.exe -m examples.import_documents

# 运行知识问答演示
.\.venv\Scripts\python.exe -m examples.rag_demo

# 比较普通检索与重新排序后的检索结果
.\.venv\Scripts\python.exe main.py
```

重复运行资料导入会重复插入资料。检索使用 `intfloat/multilingual-e5-base`，重新排序使用 `BAAI/bge-reranker-base`；首次使用时可能需要下载模型。其他独立演示的用途和运行方式见 [examples/README.md](examples/README.md)。

评估用例来自 `data/rag_test_cases.json`。两种评估现在共用 `calculate_metrics()`，保留原来的计算含义：

- `mean_recall`：至少命中一次期望主题的问题占比。这里沿用原项目的名称，计算的是主题命中率。
- `mean_precision`：每个问题中，期望主题的资料占检索结果的比例，再对全部问题取平均。
- `mean_mrr`：第一条命中资料的排名倒数，再对全部问题取平均。

没有检索结果时，该问题的三个指标均为 0。评估用例为空时显示提示，三个指标均显示为 0。检索距离筛选和重新排序规则保持原有设置。

## 运行已有测试

测试依赖单独安装在项目环境中：

```powershell
uv pip install --python .venv\Scripts\python.exe -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q
```

现有 `tests/conftest.py` 会指定 `uav_project_test` 数据库，并在每个测试前后清空其中的 `flight_analyses` 表。请先准备独立的测试数据库和表，并设置 `PASSWORD`。

当前测试中还有一个未完成的工具测试；测试组织也会让不查询数据库的用例依赖数据库。这次整理保留了这些测试文件，所以以上命令不代表全部测试已经通过。
