import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

from src.load_data import load_data
from src.updata_data import updata_data
from src.clean_data import clean_data
from src.explore_data import explore_data
from src.analyze_data import analyze_data,calculate_summary


def main():
    BASE_DIR = Path(__file__).resolve().parent
    DATA_PATH = BASE_DIR/"data"/"data.csv"
    df = load_data(DATA_PATH)
    df = clean_data(df)
    # explore_data(df)
    # analyze_data(df)
    summary = calculate_summary(df)
    print(summary)


if __name__ == "__main__":
    main()
