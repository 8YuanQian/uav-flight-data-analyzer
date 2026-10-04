from pydantic import BaseModel,Field


class FlightReport(BaseModel):
    report:str
    observations:list[str]
    limitations:list[str]

class FlightRecord(BaseModel):
    time:float = Field(ge=0)
    height:float = Field(ge=0)
    speed:float = Field(ge=0)
    battery:float = Field(ge=0,le=100)
    temperature:float

class UserQuestion(BaseModel):
    question:str


