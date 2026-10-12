from src.load_data import load_json_data
from src.document_save_to_database import save_document_to_database


def main():
    documents = load_json_data("uav_knowledge.json")
    save_document_to_database(documents)


if __name__ == "__main__":
    main()
