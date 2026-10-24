from __future__ import annotations

import asyncio
import uuid
import hashlib
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

from docqa.config import settings
from docqa.agent.answer import answer_question
from docqa.doc2md.parser import parse_document, to_markdown
from docqa.docbase.embeddings import embed_texts, model_status
from docqa.docbase.store import all_chunks, create_chat_session, db_session, delete_document as remove_document, get_chat_session, get_document_by_hash, get_image, list_chat_messages, list_chat_sessions, list_documents, list_images, save_chat_turn, save_document, save_images, update_category, update_embeddings
from docqa.models import CategoryUpdate, ChatRequest, ChatResponse, ConversationCreate, EvaluationCaseCreate
from docqa.service.llm import ModelNotConfigured
from docqa.service.evaluation import add_case, cases as evaluation_cases, evaluate as run_evaluation, remove_case
from docqa.service.watcher import status as watcher_status, watch_directory
from docqa.service.jobs import TASKS, create_job, get_job, update_job

WEB_DIR = Path(__file__).resolve().parent


async def _ingest_watched_file(path: Path) -> dict:
    with path.open("rb") as stream:
        return await upload_document(UploadFile(file=stream, filename=path.name), False, "未分类", None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = None
    if settings.watch_enabled:
        task = asyncio.create_task(watch_directory(_ingest_watched_file, delete_document), name="docqa-directory-watcher")
    else:
        from docqa.service.watcher import STATUS
        STATUS["state"] = "disabled"
    try:
        yield
    finally:
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="DocQA · 本地多模态知识问答", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "static" / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "model": settings.model, "configured": bool(settings.api_key), "documents": len(list_documents()), "retrieval": model_status()}


@app.get("/api/settings")
async def public_settings() -> dict:
    """Expose operational settings only; secrets and environment values are never returned."""
    from docqa.service.watcher import status as current_watcher_status
    return {
        "model": settings.model,
        "configured": bool(settings.api_key),
        "base_url": settings.base_url,
        "data_directory": str(settings.data_dir),
        "watcher": current_watcher_status(),
        "vision_max_images": settings.vision_max_images,
        **model_status(),
    }


@app.get("/api/watcher")
async def watcher() -> dict:
    return watcher_status()


@app.get("/api/documents")
async def documents() -> list[dict]:
    return list_documents()


@app.patch("/api/documents/{document_id}/category")
async def change_document_category(document_id: str, request: CategoryUpdate) -> dict:
    allowed = {"未分类", "课程", "项目", "论文", "技术资料", "其他"}
    if request.category not in allowed:
        raise HTTPException(status_code=422, detail="文档分类无效。")
    if not update_category(document_id, request.category):
        raise HTTPException(status_code=404, detail="文档不存在。")
    return {"updated": True, "category": request.category}


@app.delete("/api/documents/{document_id}")
async def delete_document(document_id: str) -> dict:
    item = remove_document(document_id)
    if item is None:
        raise HTTPException(status_code=404, detail="文档不存在。")
    for stored in [item["path"], *item["image_paths"], str(settings.data_dir / "markdown" / f"{document_id}.md")]:
        path = Path(stored).resolve()
        if path.is_relative_to(settings.data_dir) and path.is_file():
            path.unlink(missing_ok=True)
    image_dir = (settings.data_dir / "images" / document_id).resolve()
    if image_dir.is_relative_to(settings.data_dir) and image_dir.is_dir():
        try:
            image_dir.rmdir()
        except OSError:
            pass
    return {"deleted": True, "name": item["name"]}


@app.post("/api/documents")
async def upload_document(file: UploadFile = File(...), analyze_images: bool = Form(False), category: str = Form("未分类"), job_id: str | None = Form(None)) -> dict:
    name = Path(file.filename or "document").name
    suffix = Path(name).suffix.lower()
    if suffix not in {".pdf", ".docx", ".pptx", ".md", ".txt"}:
        raise HTTPException(status_code=415, detail="支持 PDF、DOCX、PPTX、Markdown 和 TXT 文件。")
    if category not in {"未分类", "课程", "项目", "论文", "技术资料", "其他"}:
        raise HTTPException(status_code=422, detail="文档分类无效。")
    raw = await file.read(30 * 1024 * 1024 + 1)
    if len(raw) > 30 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="单个文件不能超过 30 MB。")
    content_hash = hashlib.sha256(raw).hexdigest()
    duplicate = get_document_by_hash(content_hash)
    if duplicate:
        return {**duplicate, "chunks": 0, "images": 0, "vision_skipped": 0, "status": "unchanged", "skipped": True}
    doc_id = uuid.uuid4().hex
    destination = settings.data_dir / "uploads" / f"{doc_id}{suffix}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)
    try:
        update_job(job_id, status="processing", phase="提取文本与页面结构")
        parsed = parse_document(destination)
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="文档解析失败，请确认文件未损坏且格式正确。") from exc
    markdown = to_markdown(parsed)
    update_job(job_id, phase=f"抽取图文内容（{len(parsed.images)} 张图片）")
    chunks: list[dict] = []
    for page in parsed.pages:
        text = page.text.strip()
        if not text:
            continue
        # Paragraph-aware chunks preserve page provenance; overlap keeps boundary context.
        paragraphs = [part.strip() for part in text.split("\n") if part.strip()]
        current = ""
        for paragraph in paragraphs:
            if len(current) + len(paragraph) > 900 and current:
                chunks.append({"id": uuid.uuid4().hex, "page": page.page, "content": current})
                current = current[-120:] + "\n" + paragraph
            else:
                current = f"{current}\n{paragraph}".strip()
        if current:
            chunks.append({"id": uuid.uuid4().hex, "page": page.page, "content": current})
    image_rows = []
    image_dir = settings.data_dir / "images" / doc_id
    for image_index, extracted in enumerate(parsed.images, 1):
        image_id = uuid.uuid4().hex
        image_path = image_dir / f"{image_id}.jpg"
        try:
            with Image.open(BytesIO(extracted.data)) as source:
                source.thumbnail((1800, 1800))
                normalized = source.convert("RGB")
                image_path.parent.mkdir(parents=True, exist_ok=True)
                normalized.save(image_path, format="JPEG", quality=88, optimize=True)
        except Exception:
            continue
        caption = ""
        if analyze_images and image_index <= settings.vision_max_images and settings.api_key:
            from docqa.service.llm import describe_image
            try:
                update_job(job_id, phase=f"视觉解析图片 {image_index}/{min(len(parsed.images), settings.vision_max_images)}")
                source_page = next((page for page in parsed.pages if page.page == extracted.page), None)
                page_hint = f"文档：{name}；第 {extracted.page} 页。"
                if source_page and source_page.needs_ocr:
                    page_hint += "该 PDF 页未提取到可搜索文本，请优先逐字转写图中的可见文字。"
                elif source_page and source_page.text:
                    page_hint += f"本页正文：{source_page.text[:700]}"
                caption = await describe_image(image_path.read_bytes(), page_hint)
            except Exception:
                caption = ""
        image_rows.append({"id": image_id, "name": extracted.filename, "page": extracted.page, "path": str(image_path), "caption": caption})
        if caption:
            chunks.append({"id": uuid.uuid4().hex, "page": extracted.page, "content": f"[图片语义描述] {caption}", "image_id": image_id})
    if image_rows:
        figure_sections = ["\n\n## 图片与视觉内容"]
        for index, item in enumerate(image_rows, 1):
            relative_image = f"../images/{doc_id}/{item['id']}.jpg"
            figure_sections.append(
                f"\n\n### Figure {index} · 第 {item['page']} 页 · {item['name']}\n\n"
                f"![{name} · Figure {index} · Page {item['page']} ]({relative_image})\n\n"
                f"{item['caption'] or '图片已提取；尚未生成视觉描述。'}"
            )
        markdown += "".join(figure_sections)
    update_job(job_id, phase="建立本地检索索引")
    vectors = await asyncio.to_thread(embed_texts, [item["content"] for item in chunks])
    if vectors:
        for item, vector in zip(chunks, vectors):
            item["embedding"] = vector
            item["embedding_model"] = settings.embedding_model
    markdown_dir = settings.data_dir / "markdown"
    markdown_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = markdown_dir / f"{doc_id}.md"
    markdown_path.write_text(markdown, encoding="utf-8")
    save_document(doc_id, name, parsed.kind, len(parsed.pages), destination, markdown, chunks, content_hash, category)
    save_images(doc_id, image_rows)
    update_job(job_id, phase="保存完成")
    return {
        "id": doc_id, "name": name, "kind": parsed.kind, "pages": len(parsed.pages),
        "chunks": len(chunks), "images": len(image_rows),
        "vision_skipped": max(0, len(parsed.images) - settings.vision_max_images) if analyze_images else 0,
        "status": "ready",
    }


async def _run_upload_job(job_id: str, path: Path, name: str, analyze_images: bool, category: str) -> None:
    try:
        update_job(job_id, status="processing", phase="开始解析")
        with path.open("rb") as stream:
            result = await upload_document(UploadFile(file=stream, filename=name), analyze_images, category, job_id)
        update_job(job_id, status="completed", phase="完成", result=result)
    except HTTPException as exc:
        update_job(job_id, status="failed", phase="处理失败", error=exc.detail)
    except Exception as exc:
        update_job(job_id, status="failed", phase="处理失败", error=f"{type(exc).__name__}，请检查文件和服务日志。")
    finally:
        path.unlink(missing_ok=True)


@app.post("/api/jobs", status_code=202)
async def create_upload_job(file: UploadFile = File(...), analyze_images: bool = Form(False), category: str = Form("未分类")) -> dict:
    name = Path(file.filename or "document").name
    suffix = Path(name).suffix.lower()
    if suffix not in {".pdf", ".docx", ".pptx", ".md", ".txt"}:
        raise HTTPException(status_code=415, detail="支持 PDF、DOCX、PPTX、Markdown 和 TXT 文件。")
    if category not in {"未分类", "课程", "项目", "论文", "技术资料", "其他"}:
        raise HTTPException(status_code=422, detail="文档分类无效。")
    raw = await file.read(30 * 1024 * 1024 + 1)
    if len(raw) > 30 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="单个文件不能超过 30 MB。")
    job = create_job(name)
    job_file = settings.data_dir / "jobs" / f"{job['id']}{suffix}"
    job_file.parent.mkdir(parents=True, exist_ok=True)
    job_file.write_bytes(raw)
    task = asyncio.create_task(_run_upload_job(job["id"], job_file, name, analyze_images, category), name=f"docqa-upload-{job['id']}")
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)
    return {"id": job["id"], "status": job["status"], "filename": name}


@app.get("/api/jobs/{job_id}")
async def upload_job_status(job_id: str) -> dict:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在或服务重启后已过期。")
    return job


@app.get("/api/documents/{document_id}/markdown")
async def document_markdown(document_id: str) -> dict:
    with db_session() as db:
        row = db.execute("SELECT name,markdown FROM documents WHERE id=?", (document_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="文档不存在。")
    return {"name": row["name"], "markdown": row["markdown"]}


@app.get("/api/documents/{document_id}/images")
async def document_images(document_id: str) -> list[dict]:
    return list_images(document_id)


@app.get("/api/retrieval")
async def retrieval_trace(query: str, top_k: int = 5) -> dict:
    from docqa.docbase.retriever import retrieve_with_trace
    if not query.strip():
        raise HTTPException(status_code=422, detail="请输入检索问题。")
    return await asyncio.to_thread(retrieve_with_trace, query[:1000], max(1, min(top_k, 10)))


@app.post("/api/reindex")
async def reindex_embeddings() -> dict:
    if not settings.enable_local_embedding:
        raise HTTPException(status_code=409, detail="请在 .env 中启用 ENABLE_LOCAL_EMBEDDING=true 并重启服务。")
    chunks = all_chunks()
    if not chunks:
        return {"indexed": 0, "status": "empty"}
    vectors = await asyncio.to_thread(embed_texts, [item["content"] for item in chunks])
    if not vectors:
        raise HTTPException(status_code=503, detail="本地向量模型无法加载；请检查 sentence-transformers 安装和模型缓存。")
    update_embeddings([(item["id"], vector, settings.embedding_model) for item, vector in zip(chunks, vectors)])
    return {"indexed": len(vectors), "status": "ready", "model": settings.embedding_model}


@app.get("/api/evaluation/cases")
async def get_evaluation_cases() -> list[dict]:
    return evaluation_cases()


@app.post("/api/evaluation/cases")
async def create_evaluation_case(request: EvaluationCaseCreate) -> dict:
    return add_case(request.question, request.relevant_documents)


@app.delete("/api/evaluation/cases/{case_id}")
async def delete_evaluation_case(case_id: str) -> dict:
    if not remove_case(case_id):
        raise HTTPException(status_code=404, detail="评估样例不存在。")
    return {"deleted": True}


@app.post("/api/evaluation/run")
async def evaluate_retrieval(top_k: int = 5) -> dict:
    return await asyncio.to_thread(run_evaluation, max(1, min(top_k, 20)))


@app.get("/api/images/{image_id}")
async def image_file(image_id: str) -> FileResponse:
    image = get_image(image_id)
    if image is None or not Path(image["path"]).is_file():
        raise HTTPException(status_code=404, detail="图片不存在。")
    return FileResponse(image["path"], media_type="image/jpeg")


@app.get("/api/conversations")
async def conversations() -> list[dict]:
    return list_chat_sessions()


@app.post("/api/conversations")
async def new_conversation(request: ConversationCreate | None = None) -> dict:
    title = request.title if request else "新对话"
    return create_chat_session(title)


@app.get("/api/conversations/{conversation_id}")
async def conversation(conversation_id: str) -> dict:
    session = get_chat_session(conversation_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在。")
    return {**session, "messages": list_chat_messages(conversation_id)}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    session = get_chat_session(request.conversation_id) if request.conversation_id else None
    if request.conversation_id and session is None:
        raise HTTPException(status_code=404, detail="会话不存在，请新建会话后重试。")
    if session is None:
        session = create_chat_session()
    history = list_chat_messages(session["id"])
    try:
        answer, citations = await answer_question(request.question, history)
    except ModelNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        # Do not return exception details: HTTP client errors can contain sensitive request data.
        raise HTTPException(status_code=502, detail="DeepSeek 服务暂时不可用，请检查网络与模型配置。") from exc
    save_chat_turn(session["id"], request.question, answer, citations)
    return ChatResponse(answer=answer, citations=citations, model=settings.model, conversation_id=session["id"])
