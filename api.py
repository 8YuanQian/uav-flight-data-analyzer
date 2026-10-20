from src.load_data import load_csv_data,load_json_data
from src.clean_data import clean_data
from src.analyze_data import calculate_summary
from src.database import save_flight_analysis,get_flight_analysis,get_flight_records
from src.model import FlightRecord,FlightReport,UserQuestion,AssistantResponse
from src.llm_report import generate_flight_report
from src.flight_qa import answer_flight_question
from src.document_save_to_database import save_document_to_database
from src.rag import UAVAssistant


from fastapi import FastAPI,HTTPException,UploadFile,Query
from sentence_transformers import SentenceTransformer,CrossEncoder
from pydantic import BaseModel,Field
from pathlib import Path
from contextlib import asynccontextmanager
import psycopg
import asyncio
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR/"data"/"data.csv"


@asynccontextmanager
async def lifespan(app:FastAPI):
    rerank_model = CrossEncoder("BAAI/bge-reranker-base")
    embedding_model = SentenceTransformer("intfloat/multilingual-e5-base")
    app.state.assistant = UAVAssistant(
        rerank_model=rerank_model,
        embedding_model=embedding_model
    )

    yield

    print("free resource")

app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return{
        "status":"ok",
        "service":"uav-flight-analyzer"
    }

@app.post("/save/document")
def save_document(file:UploadFile):
    assistant = app.state.assistant
    file_object = file.file
    try:
        file_data = load_json_data(file_object)
    except pd.errors.EmptyDataError:
        raise HTTPException(status_code=400,detail="Empty file")
    except pd.errors.ParserError:
        raise HTTPException(status_code=400,detail="Invalid json format")
    
    save_document_to_database(file_data,assistant.embedding_model,"test_documents")


@app.get("/analysis/summary")
def analysis_summary():
    try:
        df = load_csv_data(DATA_PATH)
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
        file_data = load_csv_data(file_object)
    except pd.errors.EmptyDataError:
        raise HTTPException(status_code=400,detail="Empty file")
    except pd.errors.ParserError:
        raise HTTPException(status_code=400,detail="Invalid CSV format")
    
    file_columns = set(file_data.columns)
    required_columns = {"time","speed","height","battery","temperature"}
    missing_columns = required_columns - file_columns
    if missing_columns:
        raise HTTPException(status_code=422,detail=f"Missing required columns {sorted(missing_columns)}")
    
    file_data = clean_data(file_data)
    summary = calculate_summary(file_data)
    try:
        analysis_id = save_flight_analysis(file.filename,summary)
    except psycopg.Error as e:
        print(e)
        raise HTTPException(status_code=500,detail="Database Error")
    
    ai_report = generate_flight_report(summary)
    return{
        "id":analysis_id,
        "filename":file.filename,
        "content_type":file.content_type,
        "summary":summary,
        "ai_report":ai_report
    }


@app.get("/flights/{analysis_id}")
def read_flight_analysis(analysis_id:int):
    try:
        data = get_flight_analysis(analysis_id)
    except psycopg.Error:
        raise HTTPException(status_code=500,detail="Database Error")
    
    if data is None:
        raise HTTPException(status_code=404,detail="NOT FOUND")
    else:
        return data
    

@app.get("/flights")
def flight_records(limit:int = Query(default=5,ge=1,le=100)):
    try:
        data = get_flight_records(limit)
    except psycopg.Error:
        raise HTTPException(status_code=500,detail="Database Error")
    
    if data is None:
        return{
            "status":"NOT FOUND",
            "detail":"Not found any data"
        }
    return data


@app.post("/flights/model")
def answer_flight_question_to_user(question:UserQuestion):
    answer = answer_flight_question(question.question)
    return {"answer":answer}


@app.post("/assistant/query",response_model=AssistantResponse)
def use_flight_assistant_answer_query(question:UserQuestion):
    assistant = app.state.assistant
    print(f"Assistant id: {id(assistant)}")
    return assistant.ask(question.question)

