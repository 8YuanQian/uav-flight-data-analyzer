# UAV Flight Data Analyzer

使用 **Python、FastAPI、Pandas 和 Matplotlib** 开发的飞行日志分析练习项目。上传 CSV 后，服务会读取并清洗数据，返回高度、速度、温度、电量等统计摘要。

项目包含 1,000 条模拟飞行记录，用于演示数据处理和接口开发，不代表真实飞行运行数据。

## 已实现功能

- CSV 文件上传与基础格式、必需列校验。
- 使用均值填充高度缺失值，使用插值处理电量和温度缺失值。
- 返回均值、最大值、最低电量和记录数，共 8 项统计指标。
- 使用 Pydantic 校验单条 JSON 飞行记录的字段与数值范围。
- 提供 NumPy 异常筛选和 Matplotlib 绘图函数，展示飞行曲线、异常点和阈值线。
- 使用 pytest 和 TestClient 测试健康检查及正常 CSV 上传。

## 快速开始

当前版本在 Windows、Python 3.13.4 下验证。以下命令在项目根目录执行，使用项目独立环境安装依赖。

```powershell
uv venv --python 3.13
uv pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn api:app --reload
```

启动后访问交互式接口文档：<http://127.0.0.1:8000/docs>。

在 `POST /flights/analyze` 中选择 **Try it out**，上传 `data/data.csv` 并执行，即可查看统计摘要。

如果只运行服务，不需要测试工具，可使用 `requirements.txt` 安装运行依赖。macOS/Linux 使用 `.venv/bin/python` 代替 `.\.venv\Scripts\python.exe`。

## API

| 方法 | 路径 | 功能 |
| --- | --- | --- |
| GET | `/health` | 返回服务健康状态 |
| GET | `/analysis/summary` | 分析项目自带的 `data/data.csv` |
| POST | `/flights/validate` | 校验单条 JSON 飞行记录 |
| POST | `/flights/analyze` | 接收 CSV 文件并返回分析摘要 |

### CSV 输入

必需字段：`time`、`height`、`speed`、`battery`、`temperature`。其他列可以存在，但不参与统计摘要计算；`phase` 不是必需列。

```csv
time,height,speed,battery,temperature
0,100,15,90,35
1,101,16,89,36
```

上传文件的表单字段名为 `file`。例如，在 Windows PowerShell 中：

```powershell
curl.exe -X POST http://127.0.0.1:8000/flights/analyze -F "file=@data/data.csv;type=text/csv"
```

正常响应包含 `filename`、`content_type` 和 `summary`。其中 `summary` 包含：

```text
average_height
average_speed
average_temperature
max_height
max_speed
max_temperature
minimum_battery
row_count
```

输入为空或 CSV 无法解析时返回 `400`；缺少必需列时返回 `422`，并在 `detail` 中列出具体问题。

### JSON 记录校验

`POST /flights/validate` 接收：

```json
{
  "time": 0,
  "height": 100,
  "speed": 15,
  "battery": 90,
  "temperature": 35
}
```

时间、高度、速度须不小于 0，电量须在 0 到 100 之间。该模型用于 JSON 接口；CSV 接口目前主要校验文件可解析性和必需列。

## 运行测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

目前有 2 项自动化测试：

1. 健康检查返回 `200`，响应中的 `status` 为 `ok`。
2. 正常 CSV 上传返回 `200`，文件信息正确，摘要包含 1,000 条记录。

## 命令行分析

```powershell
.\.venv\Scripts\python.exe main.py
```

该命令读取自带 CSV，执行清洗并打印统计摘要。绘图函数位于 `src/plot_flightdata.py`，可在 Python 中单独调用，当前未作为 API 输出。

## 项目结构

```text
.
├── api.py                       # FastAPI 服务与请求模型
├── main.py                      # 命令行统计入口
├── requirements.txt             # 运行依赖
├── requirements-dev.txt         # 测试依赖
├── data/
│   ├── data.csv                 # 1,000 条模拟飞行记录
│   └── data_broken.csv          # 手动调试时保留的 CSV 样例
├── src/
│   ├── load_data.py             # CSV 读取
│   ├── clean_data.py            # 缺失值处理
│   ├── analyze_data.py          # Pandas 分析与摘要
│   ├── analyze_flightdata_numpy.py
│   ├── explore_data.py          # 数据探索
│   ├── plot_flightdata.py       # Matplotlib 绘图函数
│   └── updata_data.py           # CSV 写入练习
└── tests/
    └── test_api.py
```

## 后续计划

- 为异常 CSV 输入补充自动化测试，并加强数值类型和全空列校验。
- 保存与查询飞行记录和分析结果。
- 在数据处理和后端基础上继续探索大模型辅助分析与资料问答。

以上为待完成的学习计划，当前版本主要展示数据处理、API 开发与基础测试。
