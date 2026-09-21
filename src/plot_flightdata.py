import numpy as np
import matplotlib.pyplot as plt


def plot_height(flight_data, anomalies):
    time = flight_data[:,0]
    height = flight_data[:,1]
    anomalies_time = anomalies["all_anomalies"][:,0]
    anomalies_height = anomalies["all_anomalies"][:,1]
    plt.plot(time,height,label="height")
    plt.scatter(anomalies_time,anomalies_height,label="Anomalies")
    plt.legend()
    plt.title("UAV Flight Height")
    plt.xlabel("Time(s)")
    plt.ylabel("Height(m)")
    plt.show()


def plot_battery(flight_data, anomalies):
    time = flight_data[:,0]
    battery = flight_data[:,3]
    anomalies_time = anomalies["low_battery"][:,0]
    anomalies_battery = anomalies["low_battery"][:,3]
    plt.plot(time,battery,label="Battery Value")
    plt.scatter(anomalies_time,anomalies_battery,label="Anomalies Battery Value")
    plt.axhline(y=30,label="Battery Threshold")
    plt.title("UAV Battery Level")
    plt.xlabel("Time (s)")
    plt.ylabel("Battery (%)")
    plt.legend()
    plt.show()


def plot_temperature(flight_data, anomalies):
    time = flight_data[:,0]
    temperature = flight_data[:,4]
    anomalies_time = anomalies["high_temperature"][:,0]
    anomalies_temperature = anomalies["high_temperature"][:,4]
    plt.plot(time,temperature,label="Temperature")
    plt.scatter(anomalies_time,anomalies_temperature,label="High Temperature")
    plt.axhline(y=40,label="Temperature Threshold")
    plt.title("UAV Flight Temperature")
    plt.xlabel("Time (s)")
    plt.ylabel("Temperature (°C)")
    plt.legend()
    plt.show()


def plot_dashboard(flight_data, anomalies):
    time = flight_data[:,0]
    anomalies_speed_time = anomalies["high_speed"][:,0]
    anomalies_speed = anomalies["high_speed"][:,2]
    anomalies_battery_time = anomalies["low_battery"][:,0]
    anomalies_battery = anomalies["low_battery"][:,3]
    anomalies_temperature_time = anomalies["high_temperature"][:,0]
    anomalies_temperature = anomalies["high_temperature"][:,4]
    fig,axes = plt.subplots(2,2,figsize=(12,8))
    fig.suptitle("UAV Flight Dashboard")
    figure_height = axes[0,0]
    figure_speed = axes[0,1]
    figure_battery = axes[1,0]
    figure_temperature = axes[1,1]

    figure_height.plot(time,flight_data[:,1],label="Height")
    figure_height.set_title("UAV Flight Height")
    figure_height.set_xlabel("Time (s)")
    figure_height.set_ylabel("Height (m)")
    figure_height.legend()

    figure_speed.plot(time,flight_data[:,2],label="Speed")
    figure_speed.scatter(anomalies_speed_time,anomalies_speed,label="Anomalies Speed")
    figure_speed.axhline(y=20,label="Speed Threshold")
    figure_speed.set_title("UAV Flight Speed")
    figure_speed.set_xlabel("Time (s)")
    figure_speed.set_ylabel("Speed (m/s)")
    figure_speed.legend()

    figure_battery.plot(time,flight_data[:,3],label="Battery")
    figure_battery.scatter(anomalies_battery_time,anomalies_battery,label="Anomalies Battery")
    figure_battery.axhline(y=30,label="Battery Threshold")
    figure_battery.set_title("UAV Flight Battery")
    figure_battery.set_xlabel("Time (s)")
    figure_battery.set_ylabel("Battery (%)")
    figure_battery.legend()

    figure_temperature.plot(time,flight_data[:,4],label="Temperature")
    figure_temperature.scatter(anomalies_temperature_time,anomalies_temperature,label="Anomalies Temperature")
    figure_temperature.axhline(y=40,label="Temperature Threshold")
    figure_temperature.set_title("UAV Flight Temperature")
    figure_temperature.set_xlabel("Time (s)")
    figure_temperature.set_ylabel("Temperature (°C)")
    figure_temperature.legend()

    fig.tight_layout()
    plt.show()


def plot_temperature_distribution(flight_data):
    temperature = flight_data[:,4]
    mean_temperature = np.mean(temperature)
    std_temperature = np.std(temperature)
    plt.hist(temperature,bins=30)
    plt.axvline(x=mean_temperature,label="Mean Temperature")
    plt.axvline(x=mean_temperature + std_temperature,label="mean + 1 std")
    plt.axvline(x=mean_temperature - std_temperature,label="mean - 1 std")
    plt.title("UAV Temperature Distribution")
    plt.xlabel("Temperature (°C)")
    plt.ylabel("Frequency ")
    plt.legend()
    plt.show()
    print(f"Mean Temperature: {mean_temperature:.2f} °C")
    print(f"Standard Deviation: {std_temperature:.2f} °C")