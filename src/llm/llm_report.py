from openai import APIConnectionError
import pydantic
import os
import json

from src.llm.llm_client import client
from src.flight_data.prepare_flights import REPORT_FIELDS
from src.common.json_conversion import json_default
from src.schemas import FlightReport


def build_flight_report_input(flight: dict) -> dict:
    # 一次调用只描述一组飞行；采样行数不代表飞行次数。
    return {
        "uav": {
            "code": flight["uav_code"],
            "model": flight["uav_model"],
            "manufacturer": flight["manufacturer"],
        },
        "flight": {
            "csv_flight_id": flight.get("csv_flight_id"),
            "start_time": flight["start_time"].isoformat(),
            "end_time": flight["end_time"].isoformat(),
            "duration_minutes": flight["duration_minutes"],
            "sample_row_count": flight["row_count"],
        },
        "statistics": {
            **{field: flight[field] for field in REPORT_FIELDS if field != "row_count"},
            "battery_start": flight["battery_start"],
            "battery_end": flight["battery_end"],
        },
        "anomaly": {
            "status": flight["anomaly_status"],
            "reason": flight["anomaly_reason"],
        },
    }


def generate_flight_report(summary:dict, *, raise_on_error: bool = False) -> FlightReport:

    summary_json = json.dumps(summary, ensure_ascii=False, allow_nan=False, default=json_default)
    try:
        response = client.responses.create(
            model="deepseek-flash",
            instructions="""
            你负责为一条无人机飞行记录撰写简短的中文飞行报告。
            输入中的 flight 只代表一次飞行；sample_row_count 是这次飞行的采样行数，不是飞行次数。
            statistics 和 duration_minutes 已由 Python 计算，不要重新计算、推断变化趋势或跨飞行汇总。
            anomaly 只代表程序现有规则的判断，不得据此宣称符合安全标准或确认设备故障。
            不得编造阈值、测量值、位置、飞手、飞行任务或未提供的单位。

            只输出一个 JSON 对象，不要 Markdown、代码围栏或额外文字。字段必须且只能是：
            {
                "conclusion": "针对这一次飞行的一句话结论",
                "observations": ["与本次飞行有关的关键指标，避免重复罗列全部数值"],
                "attention_items": ["仅填写输入中有依据的异常或需关注事项；没有则为空数组"],
                "limitations": ["仅填写会影响本次结论的实际数据局限；没有则为空数组"]
            }
            不要在 conclusion 中重复 observations；不要把 sample_row_count 说成飞行记录数。
            """,
            input=f"""
            请只根据下面这一条飞行的结构化数据生成报告：{summary_json}
            """
            )
    except APIConnectionError:
        if raise_on_error:
            raise
        return FlightReport(
            conclusion="报告服务暂时不可用",
            observations=[],
            attention_items=[],
            limitations=[]
        )
    
    try:
        report = json.loads(response.output_text)

    except json.JSONDecodeError:
        if raise_on_error:
            raise
        report = {
            "conclusion": "报告格式无效",
            "observations": [],
            "attention_items": [],
            "limitations": []
        }

    except Exception as e:
        if raise_on_error:
            raise
        report = {
            "conclusion": "报告生成失败",
            "observations": [],
            "attention_items": [],
            "limitations": [
                str(e)
            ]
        }

    try:
        report = FlightReport.model_validate(report)
    except pydantic.ValidationError:
        if raise_on_error:
            raise
        report = FlightReport(
            conclusion="报告格式校验失败",
            observations=[],
            attention_items=[],
            limitations=[
                "模型输出不符合报告结构"
            ]
        )

    return report

