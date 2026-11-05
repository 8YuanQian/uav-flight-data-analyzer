import json
from datetime import datetime, date
from decimal import Decimal
import numpy as np


def json_default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()

    if isinstance(obj, Decimal):
        # PostgreSQL 的 NUMERIC 字段读取后是 Decimal；工具结果仍以 JSON 数值传给模型。
        return float(obj)

    if isinstance(obj, np.generic):
        return obj.item()

    if isinstance(obj, np.ndarray):
        return obj.tolist()

    raise TypeError(
        f"{type(obj).__name__} 无法JSON序列化"
    )


def serialize_tool_result(data):
    return json.dumps(
        data,
        ensure_ascii=False,
        default=json_default
    )
