from pydantic import BaseModel,Field
from sentence_transformers import SentenceTransformer,CrossEncoder


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

class Source(BaseModel):
    title:str
    url:str    

class AssistantResponse(BaseModel):
    answer:str
    sources:list[Source]

def create_transformat_model():
    embedding_model = SentenceTransformer("intfloat/multilingual-e5-base")
    rerank_model = CrossEncoder("BAAI/bge-reranker-base")
    return{
        "embedding_model":embedding_model,
        "rerank_model":rerank_model
    }
    


