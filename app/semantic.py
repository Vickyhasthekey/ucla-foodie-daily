import math
import re
from functools import lru_cache

MODEL_NAME = "BAAI/bge-small-en-v1.5"


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=MODEL_NAME)


def embed(texts):
    return [list(vector) for vector in _model().embed(list(texts))]


def cosine(left, right):
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def lexical_scores(query, documents):
    words = {word for word in re.findall(r"[a-z][a-z']+", (query or "").lower()) if len(word) >= 3}
    scores = []
    for document in documents:
        doc_words = set(re.findall(r"[a-z][a-z']+", document.lower()))
        if not words:
            scores.append(0.0)
            continue
        scores.append(len(words & doc_words) / len(words))
    return scores


def score_query(query, documents):
    if not documents:
        return []
    try:
        import fastembed  # noqa: F401

        vectors = embed([query, *documents])
    except Exception:
        return lexical_scores(query, documents)
    query_vector = vectors[0]
    return [cosine(query_vector, document) for document in vectors[1:]]
