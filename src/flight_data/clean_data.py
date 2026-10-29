"""Clean one flight's chronologically sorted samples."""

import numpy as np
import pandas as pd


def clean_data(df):
    """Fill missing measurements only within the supplied flight group."""
    cleaned = df.copy()
    for column in ("height", "speed", "battery", "temperature"):
        try:
            cleaned[column] = pd.to_numeric(cleaned[column], errors="raise")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{column} 必须是数值") from exc

    if cleaned[["height", "speed", "battery", "temperature"]].isna().all().any():
        raise ValueError("某项测量值在整次飞行中均为空，无法计算")
    if cleaned["speed"].isna().any():
        raise ValueError("speed 不允许为空")

    cleaned["height"] = cleaned["height"].fillna(cleaned["height"].mean())
    cleaned["temperature"] = cleaned["temperature"].interpolate(limit_direction="both")
    cleaned["battery"] = cleaned["battery"].interpolate(limit_direction="both")

    if not np.isfinite(cleaned[["height", "speed", "battery", "temperature"]].to_numpy(dtype=float)).all():
        raise ValueError("测量值必须是有限数值")

    if (cleaned["height"] < 0).any() or (cleaned["speed"] < 0).any():
        raise ValueError("height 和 speed 不能为负数")
    if ((cleaned["battery"] < 0) | (cleaned["battery"] > 100)).any():
        raise ValueError("battery 必须在 0 到 100 之间")
    return cleaned
