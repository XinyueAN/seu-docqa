from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from docqa.config import settings

DB_PATH = settings.data_dir / "docqa.sqlite3"


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
        pages INTEGER NOT NULL, path TEXT NOT NULL, markdown TEXT NOT NULL, sha256 TEXT,
        category TEXT NOT NULL DEFAULT '未分类',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      );
      CREATE TABLE IF NOT EXISTS chunks (
        id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        name TEXT NOT NULL, page INTEGER NOT NULL, content TEXT NOT NULL, image_id TEXT, embedding TEXT, embedding_model TEXT
      );
      CREATE TABLE IF NOT EXISTS images (
        id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        name TEXT NOT NULL, page INTEGER NOT NULL, path TEXT NOT NULL, caption TEXT NOT NULL DEFAULT ''
      );
      CREATE TABLE IF NOT EXISTS chat_sessions (
        id TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT '新对话',
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f','now')),
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f','now'))
      );
      CREATE TABLE IF NOT EXISTS chat_messages (
        id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
        position INTEGER NOT NULL, role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL,
        citations TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(session_id,position)
      );
      CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
      CREATE INDEX IF NOT EXISTS idx_images_document ON images(document_id);
      CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id, created_at);
    """)
    columns = {row[1] for row in db.execute("PRAGMA table_info(chunks)").fetchall()}
    document_columns = {row[1] for row in db.execute("PRAGMA table_info(documents)").fetchall()}
    if "sha256" not in document_columns:
        db.execute("ALTER TABLE documents ADD COLUMN sha256 TEXT")
    if "category" not in document_columns:
        db.execute("ALTER TABLE documents ADD COLUMN category TEXT NOT NULL DEFAULT '未分类'")
    if "image_id" not in columns:
        db.execute("ALTER TABLE chunks ADD COLUMN image_id TEXT")
    if "embedding" not in columns:
        db.execute("ALTER TABLE chunks ADD COLUMN embedding TEXT")
    if "embedding_model" not in columns:
        db.execute("ALTER TABLE chunks ADD COLUMN embedding_model TEXT")
    return db


@contextmanager
def db_session() -> Iterator[sqlite3.Connection]:
    db = connect()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def list_documents() -> list[dict]:
    with db_session() as db:
        rows = db.execute("SELECT d.id,d.name,d.kind,d.pages,d.category,(SELECT COUNT(*) FROM chunks c WHERE c.document_id=d.id) chunks,(SELECT COUNT(*) FROM images i WHERE i.document_id=d.id) images,d.created_at FROM documents d ORDER BY d.created_at DESC").fetchall()
    return [dict(row) for row in rows]


def get_document_by_hash(content_hash: str) -> dict | None:
    with db_session() as db:
        row = db.execute("SELECT id,name,kind,pages FROM documents WHERE sha256=?", (content_hash,)).fetchone()
    return dict(row) if row else None


def delete_document(document_id: str) -> dict | None:
    with db_session() as db:
        row = db.execute("SELECT id,name,path FROM documents WHERE id=?", (document_id,)).fetchone()
        if row is None:
            return None
        images = db.execute("SELECT path FROM images WHERE document_id=?", (document_id,)).fetchall()
        db.execute("DELETE FROM documents WHERE id=?", (document_id,))
    return {"id": row["id"], "name": row["name"], "path": row["path"], "image_paths": [item["path"] for item in images]}


def save_document(doc_id: str, name: str, kind: str, pages: int, path: Path, markdown: str, chunks: list[dict], content_hash: str | None = None, category: str = "未分类") -> None:
    with db_session() as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT OR REPLACE INTO documents(id,name,kind,pages,path,markdown,sha256,category) VALUES(?,?,?,?,?,?,?,?)", (doc_id,name,kind,pages,str(path),markdown,content_hash,category))
        db.execute("DELETE FROM chunks WHERE document_id=?", (doc_id,))
        db.executemany("INSERT INTO chunks(id,document_id,name,page,content,image_id,embedding,embedding_model) VALUES(?,?,?,?,?,?,?,?)", [
            (item["id"],doc_id,name,item["page"],item["content"],item.get("image_id"),json.dumps(item["embedding"]) if item.get("embedding") else None,item.get("embedding_model")) for item in chunks
        ])


def save_images(doc_id: str, images: list[dict]) -> None:
    with db_session() as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.executemany("INSERT OR REPLACE INTO images(id,document_id,name,page,path,caption) VALUES(?,?,?,?,?,?)", [
            (image["id"], doc_id, image["name"], image["page"], image["path"], image["caption"]) for image in images
        ])


def list_images(document_id: str) -> list[dict]:
    with db_session() as db:
        rows = db.execute("SELECT id,name,page,caption FROM images WHERE document_id=? ORDER BY page,id", (document_id,)).fetchall()
    return [dict(row) for row in rows]


def get_image(image_id: str) -> dict | None:
    with db_session() as db:
        row = db.execute("SELECT id,document_id,name,page,path,caption FROM images WHERE id=?", (image_id,)).fetchone()
    return dict(row) if row else None


def all_chunks() -> list[dict]:
    with db_session() as db:
        rows = db.execute("SELECT id,document_id,name,page,content,image_id,embedding,embedding_model FROM chunks").fetchall()
    result = [dict(row) for row in rows]
    for item in result:
        item["embedding"] = json.loads(item["embedding"]) if item["embedding"] else None
    return result


def update_embeddings(vectors: list[tuple[str, list[float], str]]) -> None:
    with db_session() as db:
        db.executemany("UPDATE chunks SET embedding=?,embedding_model=? WHERE id=?", [(json.dumps(vector), model, chunk_id) for chunk_id, vector, model in vectors])


def update_category(document_id: str, category: str) -> bool:
    with db_session() as db:
        result = db.execute("UPDATE documents SET category=? WHERE id=?", (category, document_id))
    return result.rowcount > 0


def create_chat_session(title: str = "新对话") -> dict:
    import uuid
    session_id = uuid.uuid4().hex
    with db_session() as db:
        db.execute("INSERT INTO chat_sessions(id,title) VALUES(?,?)", (session_id, title[:80]))
        row = db.execute("SELECT id,title,created_at,updated_at FROM chat_sessions WHERE id=?", (session_id,)).fetchone()
    return dict(row)


def list_chat_sessions() -> list[dict]:
    with db_session() as db:
        rows = db.execute("""
          SELECT s.id,s.title,s.created_at,s.updated_at,
            (SELECT COUNT(*) FROM chat_messages m WHERE m.session_id=s.id) message_count
          FROM chat_sessions s ORDER BY s.updated_at DESC,s.created_at DESC
        """).fetchall()
    return [dict(row) for row in rows]


def get_chat_session(session_id: str) -> dict | None:
    with db_session() as db:
        row = db.execute("SELECT id,title,created_at,updated_at FROM chat_sessions WHERE id=?", (session_id,)).fetchone()
    return dict(row) if row else None


def list_chat_messages(session_id: str) -> list[dict]:
    with db_session() as db:
        rows = db.execute("SELECT id,role,content,citations,created_at FROM chat_messages WHERE session_id=? ORDER BY position", (session_id,)).fetchall()
    result = [dict(row) for row in rows]
    for item in result:
        item["citations"] = json.loads(item["citations"] or "[]")
    return result


def save_chat_turn(session_id: str, question: str, answer: str, citations: list[dict]) -> None:
    import uuid
    with db_session() as db:
        count = db.execute("SELECT COUNT(*) FROM chat_messages WHERE session_id=?", (session_id,)).fetchone()[0]
        if count == 0:
            title = " ".join(question.split())[:42]
            if len(question) > 42:
                title += "…"
            db.execute("UPDATE chat_sessions SET title=? WHERE id=?", (title or "新对话", session_id))
        db.execute("INSERT INTO chat_messages(id,session_id,position,role,content) VALUES(?,?,?,?,?)", (uuid.uuid4().hex, session_id, count + 1, "user", question))
        db.execute("INSERT INTO chat_messages(id,session_id,position,role,content,citations) VALUES(?,?,?,?,?,?)", (uuid.uuid4().hex, session_id, count + 2, "assistant", answer, json.dumps(citations, ensure_ascii=False)))
        db.execute("UPDATE chat_sessions SET updated_at=strftime('%Y-%m-%d %H:%M:%f','now') WHERE id=?", (session_id,))
