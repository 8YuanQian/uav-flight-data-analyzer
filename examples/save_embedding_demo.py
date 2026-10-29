import json
from pathlib import Path
import numpy as np

from src.rag.embedding import create_embedding


DATABASE_PATH = Path(__file__).resolve().parent.parent/"data"/"documents.json"
EMBEDDINGBASE_PATH = Path(__file__).resolve().parent.parent/"data"/"document_embedding.npy"


def save_embedding_document(document, embedding_model):
    document_embedding = create_embedding(document, embedding_model)
    np.save(EMBEDDINGBASE_PATH,document_embedding)