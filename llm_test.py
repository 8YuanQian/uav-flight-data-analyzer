from openai import OpenAI
import os 
import json

api_key = os.getenv("DEEPSEEK_API_KEY")

client = OpenAI(
    api_key=api_key,
    base_url="https://api.deepseek.com"
)

summary = {
    "average_height": 101.5,
    "average_speed": 14.8,
    "battery_used": 18.4,
    "max_temperature": 41.2
}
summary_json = json.dumps(summary,indent=2)


response = client.responses.create(
    model="deepseek-flash",

    instructions="""
    You are a UAV flight analysis assistant.
    Use only the data provided by the Python program.
    Do not invent measurements.
    Write a concise flight report.
    Please reply in Chinese.
    """,

    input=f"""
    Analyze the following UAV flight data:

    {summary_json}
    """
)
print(response.output_text)



