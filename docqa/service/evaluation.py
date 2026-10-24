from __future__ import annotations

import json
import uuid
from docqa.config import settings
from docqa.docbase.retriever import retrieve


DATASET_PATH = settings.data_dir / "evaluation.json"


def cases() -> list[dict]:
    if not DATASET_PATH.is_file():
        return []
    try:
        return json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def add_case(question: str, relevant_documents: list[str]) -> dict:
    items = cases()
    item = {"id": uuid.uuid4().hex, "question": question.strip(), "relevant_documents": sorted({name.strip() for name in relevant_documents if name.strip()})}
    items.append(item)
    DATASET_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATASET_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return item


def remove_case(case_id: str) -> bool:
    items = cases()
    remaining = [item for item in items if item.get("id") != case_id]
    if len(remaining) == len(items):
        return False
    DATASET_PATH.write_text(json.dumps(remaining, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def evaluate(top_k: int = 5) -> dict:
    dataset = cases()
    if not dataset:
        return {"cases": 0, "recall_at_k": 0, "hit_rate": 0, "mrr": 0, "details": []}
    hits = 0
    recall_scores = []
    reciprocal_ranks = []
    details = []
    for item in dataset:
        relevant = set(item["relevant_documents"])
        results = retrieve(item["question"], top_k)
        ranked_names = [result["name"] for result in results]
        relevant_positions = [index + 1 for index, name in enumerate(ranked_names) if name in relevant]
        hit = bool(relevant_positions)
        hits += int(hit)
        recall_scores.append(len(set(ranked_names) & relevant) / max(len(relevant), 1))
        reciprocal_ranks.append(1 / min(relevant_positions) if hit else 0)
        details.append({"id": item["id"], "question": item["question"], "expected": sorted(relevant), "retrieved": ranked_names, "hit": hit, "reciprocal_rank": reciprocal_ranks[-1]})
    count = len(dataset)
    return {"cases": count, "top_k": top_k, "recall_at_k": round(sum(recall_scores) / count, 4), "hit_rate": round(hits / count, 4), "mrr": round(sum(reciprocal_ranks) / count, 4), "details": details}
