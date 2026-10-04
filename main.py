import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import json
from pathlib import Path

from src.llm_client import client
from src.load_data import load_csv_data,load_data_json_data
from src.updata_data import updata_data
from src.clean_data import clean_data
from src.explore_data import explore_data
from src.analyze_data import analyze_data,calculate_summary
from src.llm_report import generate_flight_report
from src.retrieve import retrieve
from src.embedding import create_embedding
from src.database import get_flight_records,save_flight_analysis,get_flight_analysis
from src.document_store import save_document
from src.context import build_context
from src.prompt import build_prompt
from src.llm import ask_llm
from src.rag import UAVAasistent
from src.document_save_to_database import save_document_to_database
from src.evaluation import evaluation_retrieval_rerank, evaluation_retrieval_without_rerank
from tools.flights_tools import get_latest_flight_analysis
from tools_calling_demo import answer_flight_question


BASE_DIR = Path(__file__).resolve()
PX4_INFORMATION = BASE_DIR/"reference"/"px4_log_notes.json"

def main():
    # uav_assistant = UAVAasistent()
    # query = input("question: ")
    # print(uav_assistant.ask(query))
    # data = load_data_json_data("uav_knowledge.json")
    # save_document_to_database(data)
    # evaluation_retrieval_rerank("rag_test_cases.json")
    # assistant = UAVAasistent()
    # query = input("question: ")
    # answer = assistant.ask(query)
    # print(f"Answer: {answer}")
    print("===========retrieval===========")
    evaluation_retrieval_without_rerank("rag_test_cases.json")
    print()
    print("===========retrieval + rerank===========")
    evaluation_retrieval_rerank("rag_test_cases.json")





if __name__ == "__main__":
    main()
