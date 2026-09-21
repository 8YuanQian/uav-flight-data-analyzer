import numpy as np


def calculate_statistics(flight_data):
    average = np.mean(flight_data,axis=0)
    highest = np.max(flight_data,axis=0)
    lowest = np.min(flight_data,axis=0)
    return {
        "average_height":average[1],
        "average_speed":average[2],
        "average_temperature":average[4],
        "highest_height":highest[1],
        "highest_speed":highest[2],
        "highest_temperature":highest[4],
        "lowest_battery":lowest[3]
        }


def detect_anomalies(flight_data):
    mask_low_battery = flight_data[:,3] < 30
    mask_high_temperature = flight_data[:,4] > 40
    mask_high_speed = flight_data[:,2] > 20
    mask_dangerous = (flight_data[:,3] < 30) & (flight_data[:,4] > 40) 
    mask_any_anomaly = (mask_high_speed) | (mask_high_temperature) | (mask_low_battery)
    return {
        "low_battery": flight_data[mask_low_battery],
        "high_temperature": flight_data[mask_high_temperature],
        "high_speed": flight_data[mask_high_speed],
        "dangerous": flight_data[mask_dangerous],
        "all_anomalies": flight_data[mask_any_anomaly]
    }


def print_report(statistics,anomalies):
    print("===== UAV Flight Analysis =====")
    print()
    print(f"Average Height: {statistics['average_height']:.2f} m")
    print(f"Average speed: {statistics['average_speed']:.2f} m/s")
    print(f"Average Temperature: {statistics['average_temperature']:.2f} °C")
    print()
    print(f"Highest Height: {statistics['highest_height']:.2f} m")
    print(f"Highest speed: {statistics['highest_speed']:.2f} m/s")
    print(f"Highest Temperature: {statistics['highest_temperature']:.2f} °C")
    print(f"Lowest Battery: {statistics['lowest_battery']:.2f} %")
    print()
    print("===== Anomalies =====")
    print()
    print(f"Low Battery Records: {len(anomalies['low_battery'])}")
    print()
    print(f"High Temperature Records: {len(anomalies['high_temperature'])}")
    print()
    print(f"High Speed Records: {len(anomalies['high_speed'])}")
    print()
    print(f"Dangerous Records: {len(anomalies['dangerous'])}")


    def standardize_features(flight_data):
        height = flight_data[:,1]
        speed = flight_data[:,2]
        temperature = flight_data[:,4]
        features = np.column_stack((height,speed,temperature))
        mean = np.mean(features,axis=0)
        std = np.std(features,axis=0)
        standardize = (features - mean) / std
        return standardize