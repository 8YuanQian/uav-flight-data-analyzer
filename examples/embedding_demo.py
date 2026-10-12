from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np


def get_cosine_similarity(query_embedding,document_embedding):
    similarity_array = cosine_similarity(
        query_embedding.reshape(1,-1),
        document_embedding
    )
    return similarity_array


def main():
    documents = [
        "无人机电池电量低于20%时应该立即返航",
        "无人机飞行过程中需要保持稳定高度",
        "无人机起飞前需要检查螺旋桨"
    ]

    query = "什么时候无人机会自动回来"

    model = SentenceTransformer(
        "intfloat/multilingual-e5-base"
    )

    document_embedding = model.encode(documents)
    query_embedding = model.encode(query)

    embedding_array = get_cosine_similarity(query_embedding,document_embedding)
    print(embedding_array)

    index = np.argmax(embedding_array)
    print(documents[index])


if __name__ == "__main__":
    main()
