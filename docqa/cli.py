from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from starlette.datastructures import UploadFile
from fastapi import HTTPException

from docqa.agent.answer import answer_question
from docqa.docbase.store import list_documents
from docqa.service.evaluation import evaluate
from docqa.web.app import upload_document

SUPPORTED = {".pdf", ".docx", ".pptx", ".md", ".txt"}


async def _ingest(path: Path, analyze_images: bool) -> dict:
    with path.open("rb") as stream:
        return await upload_document(UploadFile(file=stream, filename=path.name), analyze_images, "未分类", None)


def build_directory(directory: Path, recursive: bool, analyze_images: bool) -> int:
    if not directory.is_dir():
        print(f"目录不存在：{directory}", file=sys.stderr)
        return 2
    paths = directory.rglob("*") if recursive else directory.iterdir()
    files = sorted(path for path in paths if path.is_file() and path.suffix.lower() in SUPPORTED)
    if not files:
        print("没有找到支持的文档（PDF / DOCX / PPTX / MD / TXT）。")
        return 0
    failed = 0
    for index, path in enumerate(files, 1):
        print(f"[{index}/{len(files)}] 正在处理：{path.name}")
        try:
            result = asyncio.run(_ingest(path, analyze_images))
            if result.get("skipped"):
                print("  跳过 · 内容已存在")
            else:
                print(f"  完成 · {result['pages']} 页 · {result['chunks']} 个片段 · {result['images']} 张图片")
        except Exception as exc:
            failed += 1
            message = exc.detail if isinstance(exc, HTTPException) else str(exc)
            print(f"  失败 · {type(exc).__name__}: {message}", file=sys.stderr)
    print(f"\n构建结束：成功 {len(files)-failed}，失败 {failed}。当前库共 {len(list_documents())} 份文档。")
    return 1 if failed else 0


def query(question: str) -> int:
    try:
        answer, citations = asyncio.run(answer_question(question))
    except Exception as exc:
        print(f"问答失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(answer)
    if citations:
        print("\n来源：")
        for citation in citations:
            print(f"- {citation['document']} · 第 {citation['page']} 页 · {citation['id']}")
            print(f"  {citation['excerpt'][:220]}")
    return 0


def test_retrieval(top_k: int) -> int:
    result = evaluate(top_k)
    print(json.dumps({key: value for key, value in result.items() if key != "details"}, ensure_ascii=False, indent=2))
    for item in result.get("details", []):
        state = "命中" if item["hit"] else "未命中"
        print(f"[{state}] {item['question']} · 期望 {', '.join(item['expected'])} · 检索 {', '.join(item['retrieved'])}")
    if result["cases"] == 0:
        print("评估集中还没有样例，请在 Web 检索评估页面添加问题及预期来源。")
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="docqa", description="知序 DocQA 本地文档知识库工具")
    commands = parser.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build", help="解析目录并构建本地知识库")
    build_parser.add_argument("directory", type=Path, help="文档目录")
    build_parser.add_argument("--no-recursive", action="store_true", help="不遍历子目录")
    build_parser.add_argument("--vision", action="store_true", help="明确允许将最多配置上限的图片发送至 DeepSeek Flash 分析")
    query_parser = commands.add_parser("query", help="使用本地知识库回答问题")
    query_parser.add_argument("question", help="自然语言问题")
    test_parser = commands.add_parser("test", help="运行本地检索评估集")
    test_parser.add_argument("--top-k", type=int, default=5)
    commands.add_parser("list", help="列出已入库文档")
    args = parser.parse_args()
    if args.command == "build":
        return build_directory(args.directory.resolve(), not args.no_recursive, args.vision)
    if args.command == "query":
        return query(args.question)
    if args.command == "test":
        return test_retrieval(max(1, min(args.top_k, 20)))
    if args.command == "list":
        for item in list_documents():
            print(f"{item['name']} · {item['kind']} · {item['pages']} 页 · {item['chunks']} 片段 · {item['images']} 图片")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
