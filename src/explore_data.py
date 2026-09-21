import pandas as pd

def explore_data(df):
    print("===== Dataset Info =====")
    df.info()
    print()
    print("===== Statistics =====")
    print(df.describe())
    print()
    print("===== Missing Values =====")
    print(df.isnull().sum())
    print()
    print("===== Correlation =====")
    print(df.corr())