from pathlib import Path

from sentence_transformers import SentenceTransformer

from src.flight_data.load_data import load_json_data
from src.rag.document_save_to_database import save_document_to_database


def main():
    data_path = Path(__file__).resolve().parents[1] / "data" / "uav_knowledge.json"
    with data_path.open(encoding="utf-8") as file:
        documents = load_json_data(file)
    embedding_model = SentenceTransformer("intfloat/multilingual-e5-base")
    save_document_to_database(documents, embedding_model, "documents")


if __name__ == "__main__":
    main()
