from src.load_data import load_data
from src.clean_data import clean_data
from src.analyze_data import calculate_summary

from fastapi import FastAPI,HTTPException,UploadFile
from pydantic import BaseModel,Field
from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR/"data"/"data.csv"
app = FastAPI()

class FlightRecord(BaseModel):
    time:float = Field(ge=0)
    height:float = Field(ge=0)
    speed:float = Field(ge=0)
    battery:float = Field(ge=0,le=100)
    temperature:float

@app.get("/health")
def health():
    return{
        "status":"ok",
        "service":"uav-flight-analyzer"
    }


@app.get("/analysis/summary")
def analysis_summary():
    try:
        df = load_data(DATA_PATH)
    except FileNotFoundError:
        raise HTTPException(status_code=500,detail="Flight data file is unavailable")
    df = clean_data(df)
    return calculate_summary(df)


@app.post("/flights/validate")
def flights_validate(record : FlightRecord):
    record_data = record.model_dump()
    return {
        "status":"valid",
        "record":record_data
    }


@app.post("/flights/analyze")
def analyze_flights_csv(file:UploadFile):
    file_object = file.file
    try:
        file_data = load_data(file_object)
    except pd.errors.EmptyDataError:
        raise HTTPException(status_code=400,detail="Uploaded CSV is empty")
    except pd.errors.ParserError:
        raise HTTPException(status_code=400,detail="Invalid CSV format")
    
    file_columns = set(file_data.columns)
    required_columns = {"time","speed","height","battery","temperature"}
    missing_columns = required_columns - file_columns
    if missing_columns:
        raise HTTPException(status_code=422,detail=f"Missing required columns:{sorted(missing_columns)}")
    
    file_data = clean_data(file_data)
    summary = calculate_summary(file_data)
    return{
        "filename":file.filename,
        "content_type":file.content_type,
        "summary":summary
    }