import pandas as pd
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]


def load_csv_data(file_object):
    # 飞行编号是用户标识，不能把 001 转成数字 1。
    df = pd.read_csv(file_object, converters={"flight_id": lambda value: value})
    return df

def load_json_data(file_object):
    data = json.load(file_object)
    return data
