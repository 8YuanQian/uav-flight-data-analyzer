import pandas as pd

def analyze_data(df):
    print(df.nlargest(10,"height"))
    print(df.nsmallest(10,"battery"))
    print(df.groupby("phase").agg(
    {
        "height":"mean",
        "speed":"mean",
        "battery":"mean"
    }
    ))


def detect_anomalies_dataframe(df):
    low_battery = df["battery"] < 30
    high_speed_temperature = (df["speed"] > 18) & (df["temperature"] > 38)
    return {
        "low_battery":df[low_battery],
        "high_speed_temperature":df[high_speed_temperature],
        "data":df
        }


def calculate_summary(df):
    row_count = df.shape[0]
    return {
        "average_height" : float(df["height"].mean()),
        "average_speed" : float(df["speed"].mean()),
        "average_temperature" : float(df["temperature"].mean()),
        "max_height" : float(df["height"].max()),
        "max_speed" : float(df["speed"].max()),
        "max_temperature" : float(df["temperature"].max()),
        "minimum_battery" : float(df["battery"].min()),
        "row_count" : row_count
    }