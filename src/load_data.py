import pandas as pd
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def load_csv_data(file_object):
    df = pd.read_csv(file_object)
    return df

def load_json_data(file_object):
    data = json.load(file_object)
    return data
