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
        "average_height": round(float(df["height"].mean()), 2),
        "average_speed": round(float(df["speed"].mean()), 2),
        "average_temperature": round(float(df["temperature"].mean()), 2),

        "max_height": round(float(df["height"].max()), 2),
        "max_speed": round(float(df["speed"].max()), 2),
        "max_temperature": round(float(df["temperature"].max()), 2),

        "minimum_battery": round(float(df["battery"].min()), 2),

        "row_count": row_count
    }