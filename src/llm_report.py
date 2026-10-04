from openai import APIConnectionError
import pydantic
import os
import json

from src.llm_client import client
from src.model import FlightReport


def generate_flight_report(summary:dict) -> FlightReport:

    summary_json = json.dumps(summary,indent=2)
    try:
        response = client.responses.create(
            model="deepseek-flash",
            instructions="""
            You are a UAV flight analysis assistant.

            Return ONLY valid JSON.
            Do not use Markdown.
            Do not add explanations outside JSON.

            The output must follow this format:

            {
                "report": "string",
                "observations": [
                    "string"
                ],
                "limitations": [
                    "string"
                ]
            }

            Use only the data provided by the Python program.
            Do not invent measurements or thresholds.

            Please reply in Chinese.
            """,
            input=f"""
            Analyze the following UAV flight data:{summary_json}
            """
            )
    except APIConnectionError:
        return FlightReport(
            report="Connextion Error",
            observations=[],
            limitations=[]
        )
    
    try:
        report = json.loads(response.output_text)

    except json.JSONDecodeError:
        report = {
            "report": "Invalid JSON returned by LLM",
            "observations": [],
            "limitations": []
        }

    except Exception as e:
        report = {
            "report": "Unexpected error",
            "observations": [],
            "limitations": [
                str(e)
            ]
        }

    try:
        report = FlightReport(**report)
    except pydantic.ValidationError:
        report = FlightReport(
            report="Invalid response from LLM.",
            observations=[],
            limitations=[
                "LLM output format validation failed."
            ]
        )

    return report

