from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class FlightReport(BaseModel):
    report:str
    observations:list[str]
    limitations:list[str]

class FlightRecord(BaseModel):
    """Validate one CSV time interval before grouping it with a flight."""

    uav_code: str = Field(min_length=1)
    uav_model: str = Field(min_length=1)
    manufacturer: str = Field(min_length=1)
    flight_id: str = Field(min_length=1)
    start_time: str = Field(pattern=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
    end_time: str = Field(pattern=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
    height: float = Field(ge=0)
    speed: float = Field(ge=0)
    battery: float = Field(ge=0, le=100)
    temperature: float

    @model_validator(mode="after")
    def validate_interval(self):
        try:
            started = datetime.strptime(self.start_time, "%Y-%m-%d %H:%M")
            ended = datetime.strptime(self.end_time, "%Y-%m-%d %H:%M")
        except ValueError as exc:
            raise ValueError("时间必须是真实的 YYYY-MM-DD HH:mm") from exc
        if ended <= started:
            raise ValueError("end_time 必须晚于 start_time")
        return self


class FlightAnalysisUpdate(BaseModel):
    """完整替换分析记录的可修改字段，version 为客户端读到的版本。"""

    version: int = Field(ge=1)
    filename: str = Field(min_length=1)
    row_count: int
    average_height: float
    average_speed: float
    average_temperature: float
    max_height: float
    max_speed: float
    max_temperature: float
    minimum_battery: float


class UavCreate(BaseModel):
    uav_code: str = Field(min_length=1)
    uav_model: str = Field(min_length=1)
    manufacturer: str = Field(min_length=1)


class FlightRecordUpdate(BaseModel):
    """Replace a calculated flight summary using optimistic locking."""

    version: int = Field(ge=1)
    filename: str = Field(min_length=1)
    start_time: datetime
    end_time: datetime
    row_count: int = Field(ge=1)
    average_height: float
    max_height: float
    average_speed: float
    max_speed: float
    battery_start: float = Field(ge=0, le=100)
    battery_end: float = Field(ge=0, le=100)
    minimum_battery: float = Field(ge=0, le=100)
    average_temperature: float
    max_temperature: float
    anomaly_status: str
    anomaly_reason: str | None = None

class UserQuestion(BaseModel):
    question:str
    thread_id: UUID | None = None

class Source(BaseModel):
    title:str
    url:str    

class AssistantResponse(BaseModel):
    answer:str
    sources:list[Source]
    thread_id: str
