import pandas as pd
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def load_csv_data(filename):
    df = pd.read_csv(filename)
    return df

def load_data_json_data(filename):
    with open(BASE_DIR/"data"/filename,"r",encoding="utf-8") as file:
        data = json.load(file)
        return data
