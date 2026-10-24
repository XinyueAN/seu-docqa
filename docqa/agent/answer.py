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


def _contextual_query(question: str, history: list[dict]) -> str:
    previous_user = next((item["content"] for item in reversed(history) if item.get("role") == "user"), "")
    follow_up = len(question.strip()) <= 28 or bool(re.search(r"(它|这个|那个|上述|前面|刚才|其|继续|具体|为什么|怎么做|再说说)", question))
    return f"{previous_user[-180:]}\n{question}" if previous_user and follow_up else question


async def answer_question(question: str, history: list[dict] | None = None) -> tuple[str, list[dict]]:
    history = history or []
    evidence = await asyncio.to_thread(_retrieve_evidence, _contextual_query(question, history))
    if not evidence:
        return "知识库中还没有可用于回答的文档内容。请先添加 PDF、Word、PPT、Markdown 或 TXT 文档。", []
    context = "\n\n".join(
        f"[S{i} | {item['name']} | 第{item['page']}页]\n{item['content']}" for i, item in enumerate(evidence, 1)
    )
    system_prompt = (
        "你是知序 DocQA 文档问答 Agent。遵守下面的项目工作约定。历史对话只帮助理解简称和承接语境，"
        "历史回答不能作为事实依据；事实只能依据本轮新检索的证据。证据不足时明确说明，不得伪造事实、文档名、页码或图片内容。引用证据时使用 [S1] 格式。"
        "如果证据能支持流程、架构或步骤说明，使用 Mermaid flowchart 给出可核验的图示。\n\n"
        f"项目约定文件 AGENTS.md：\n{_project_contract()}"
    )
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(
        {"role": item["role"], "content": item["content"][:3000]}
        for item in history[-6:] if item.get("role") in {"user", "assistant"}
    )
    messages.append({"role": "user", "content": f"当前问题：{question}\n\n本轮新检索证据：\n{context}"})
    answer = await complete(messages)
    citations = [{
        "id": f"S{i}", "document": item["name"], "page": item["page"],
        "excerpt": item["content"][:360], "score": item["fusion_score"],
        "image_url": f"/api/images/{item['image_id']}" if item.get("image_id") else None,
    } for i, item in enumerate(evidence, 1)]
    return answer, citations
