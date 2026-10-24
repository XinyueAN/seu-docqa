from __future__ import annotations

from functools import lru_cache

from docqa.config import settings


@lru_cache(maxsize=1)
def _embedding_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(settings.embedding_model)


@lru_cache(maxsize=1)
def _reranker_model():
    from sentence_transformers import CrossEncoder
    return CrossEncoder(settings.reranker_model)


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    if not settings.enable_local_embedding or not texts:
        return None
    try:
        vectors = _embedding_model().encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return vectors.tolist()
    except Exception:
        return None


def rerank(query: str, candidates: list[dict]) -> list[dict]:
    if not settings.enable_local_reranker or not candidates:
        return candidates
    try:
        scores = _reranker_model().predict([[query, item["content"][:2000]] for item in candidates], show_progress_bar=False)
        return [
            {**item, "rerank_score": float(score)}
            for item, score in sorted(zip(candidates, scores), key=lambda pair: float(pair[1]), reverse=True)
        ]
    except Exception:
        return candidates


def model_status() -> dict:
    return {
        "embedding_enabled": settings.enable_local_embedding,
        "embedding_model": settings.embedding_model,
        "reranker_enabled": settings.enable_local_reranker,
        "reranker_model": settings.reranker_model,
        "note": "首次启用会在本机下载模型权重；下载和推理均不发送文档到模型服务。",
    }
