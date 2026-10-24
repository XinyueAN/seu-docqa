from __future__ import annotations

import asyncio
import re
from collections import defaultdict

from docqa.config import ROOT_DIR
from docqa.docbase.retriever import retrieve
from docqa.service.llm import complete


def _project_contract() -> str:
    contract = ROOT_DIR / "AGENTS.md"
    try:
        return contract.read_text(encoding="utf-8")[:12000]
    except OSError:
        return "回答必须基于检索证据；证据不足时明确说明。"


def _retrieve_evidence(question: str, top_k: int = 5) -> list[dict]:
    parts = [part.strip() for part in re.split(r"[？?；;。\n]+|并且|以及|同时", question) if len(part.strip()) >= 3]
    queries = list(dict.fromkeys([question.strip(), *parts]))[:4]
    fusion: dict[str, float] = defaultdict(float)
    items_by_id: dict[str, dict] = {}
    for query in queries:
        for rank, item in enumerate(retrieve(query, top_k), 1):
            fusion[item["id"]] += 1 / (60 + rank)
            items_by_id[item["id"]] = item
    return [{**items_by_id[key], "fusion_score": round(fusion[key], 5)} for key in sorted(fusion, key=fusion.get, reverse=True)[:top_k]]


async def answer_question(question: str) -> tuple[str, list[dict]]:
    evidence = await asyncio.to_thread(_retrieve_evidence, question)
    if not evidence:
        return "知识库中还没有可用于回答的文档内容。请先添加 PDF、Word、PPT、Markdown 或 TXT 文档。", []
    context = "\n\n".join(
        f"[S{i} | {item['name']} | 第{item['page']}页]\n{item['content']}" for i, item in enumerate(evidence, 1)
    )
    system_prompt = (
        "你是知序 DocQA 文档问答 Agent。遵守下面的项目工作约定，并且只能依据本轮给出的检索证据回答。"
        "证据不足时明确说明，不得伪造事实、文档名、页码或图片内容。引用证据时使用 [S1] 格式。"
        "如果证据能支持流程、架构或步骤说明，使用 Mermaid flowchart 给出可核验的图示。\n\n"
        f"项目约定文件 AGENTS.md：\n{_project_contract()}"
    )
    answer = await complete([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"问题：{question}\n\n检索证据：\n{context}"},
    ])
    citations = [{
        "id": f"S{i}", "document": item["name"], "page": item["page"],
        "excerpt": item["content"][:360], "score": item["fusion_score"],
        "image_url": f"/api/images/{item['image_id']}" if item.get("image_id") else None,
    } for i, item in enumerate(evidence, 1)]
    return answer, citations
