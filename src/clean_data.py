import pandas as pd

def clean_data(df):
    df["height"] = df["height"].fillna(df["height"].mean())
    df["temperature"] = df["temperature"].interpolate(limit_direction = "both")
    df["battery"] = df["battery"].interpolate(limit_direction = "both")
    return df