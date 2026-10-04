import json
from pathlib import Path
import numpy as np

from embedding import create_embedding


DATABASE_PATH = Path(__file__).resolve().parent.parent/"data"/"documents.json"
EMBEDDINGBASE_PATH = Path(__file__).resolve().parent.parent/"embedding"/"document_embedding.npy"


def save_embedding_document(document):
    document_embedding = create_embedding(document)
    np.save(EMBEDDINGBASE_PATH,document_embedding)