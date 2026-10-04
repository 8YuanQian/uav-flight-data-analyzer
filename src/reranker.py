from sentence_transformers import CrossEncoder

model_reranker = CrossEncoder("BAAI/bge-reranker-base")

def rerank_documents(query, documents, top_k=3):
    if not documents:
        return []

    # Prepare the input for the reranker model
    reranker_input = [(query, doc['content']) for doc in documents]

    # Get the relevance scores from the reranker model
    scores = model_reranker.predict(reranker_input)

    # Combine documents with their scores
    scored_documents = [{'document': doc, 'score': score} for doc, score in zip(documents, scores)]

    # Sort documents by score in descending order
    scored_documents.sort(key=lambda x: x['score'], reverse=True)

    # Return the top_k documents
    return [{"content":doc['document']['content'], "source":doc['document']['source'],  "metadata":doc['document']['metadata'], "score":doc["score"], "distance":doc["document"]["distance"]} for doc in scored_documents[:top_k] if doc["score"] > 0]
