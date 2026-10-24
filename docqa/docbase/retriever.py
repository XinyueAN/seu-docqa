from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

from docqa.config import settings
from docqa.docbase.embeddings import rerank
from docqa.docbase.store import all_chunks


def terms(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9_]+|[\u3400-\u9fff]+", text.lower())
    result = []
    for token in tokens:
        if re.fullmatch(r"[\u3400-\u9fff]+", token):
            result.extend(token)
            result.extend(token[i:i+2] for i in range(len(token) - 1))
        else:
            result.append(token)
    return result


def retrieve_with_trace(query: str, top_k: int = 5) -> dict:
    chunks = all_chunks()
    if not chunks:
        return {"query": query, "lanes": {"bm25": [], "tfidf": [], "dense": []}, "fused": [], "results": [], "models": {"embedding": settings.embedding_model, "embedding_enabled": settings.enable_local_embedding, "reranker": settings.reranker_model, "reranker_enabled": settings.enable_local_reranker}}
    q = Counter(terms(query))
    docs = [Counter(terms(item["content"])) for item in chunks]
    n = len(chunks)
    df = Counter(term for document in docs for term in document.keys())
    avg_len = sum(sum(document.values()) for document in docs) / max(n, 1)
    bm25, tfidf, dense = [], [], []
    q_tfidf = {term: (1 + math.log(count)) * math.log(1 + n / (df[term] + 1)) for term, count in q.items()}
    q_norm = math.sqrt(sum(value * value for value in q_tfidf.values())) or 1
    for index, (chunk, document) in enumerate(zip(chunks, docs)):
        length = sum(document.values())
        score = 0.0
        for term, count in document.items():
            idf = math.log(1 + (n - df[term] + .5) / (df[term] + .5))
            score += idf * count * 2.2 / (count + 1.2 * (.25 + .75 * length / max(avg_len, 1)))
        bm25.append((index, score))
        sparse_doc = {term: (1 + math.log(count)) * math.log(1 + n / (df[term] + 1)) for term, count in document.items()}
        dot = sum(value * sparse_doc.get(term, 0) for term, value in q_tfidf.items())
        d_norm = math.sqrt(sum(value * value for value in sparse_doc.values())) or 1
        tfidf.append((index, dot / (q_norm * d_norm)))
        stored = chunk.get("embedding")
        if stored and chunk.get("embedding_model") == settings.embedding_model:
            dense.append((index, stored))
    lanes: dict[str, list[tuple[int, float]]] = {"bm25": bm25, "tfidf": tfidf, "dense": []}
    if settings.enable_local_embedding and dense:
        try:
            from docqa.docbase.embeddings import embed_texts
            query_vector = embed_texts([query])
            if query_vector:
                qv = query_vector[0]
                lanes["dense"] = [(i, sum(a*b for a,b in zip(vector,qv))) for i, vector in dense]
        except Exception:
            pass
    lane_rows = {}
    fused_ranks: dict[int, float] = defaultdict(float)
    lane_membership: dict[int, dict[str, float]] = defaultdict(dict)
    for lane, ranked in lanes.items():
        ranked = sorted(ranked, key=lambda pair: pair[1], reverse=True)
        if lane != "dense":
            ranked = [pair for pair in ranked if pair[1] > 0]
        rows = []
        for rank, (index, score) in enumerate(ranked[:max(top_k * 4, 12)], 1):
            fused_ranks[index] += 1 / (60 + rank)
            lane_membership[index][lane] = round(float(score), 5)
            rows.append({"chunk_id": chunks[index]["id"], "document": chunks[index]["name"], "page": chunks[index]["page"], "score": round(float(score), 5), "excerpt": chunks[index]["content"][:240], "image_id": chunks[index].get("image_id")})
        lane_rows[lane] = rows[:top_k]
    candidate_indices = sorted(fused_ranks, key=fused_ranks.get, reverse=True)[:max(top_k * 4, 12)]
    fused = [{**chunks[i], "fusion_score": round(fused_ranks[i], 5), "lane_scores": lane_membership[i]} for i in candidate_indices]
    reranked = rerank(query, fused)
    results = reranked[:top_k]
    return {
        "query": query,
        "lanes": lane_rows,
        "fused": [{"chunk_id": item["id"], "document": item["name"], "page": item["page"], "score": item["fusion_score"], "lane_scores": item["lane_scores"], "excerpt": item["content"][:240]} for item in fused[:top_k]],
        "results": results,
        "models": {"embedding": settings.embedding_model, "embedding_enabled": settings.enable_local_embedding, "reranker": settings.reranker_model, "reranker_enabled": settings.enable_local_reranker},
    }


def retrieve(query: str, top_k: int = 5) -> list[dict]:
    return retrieve_with_trace(query, top_k)["results"]
