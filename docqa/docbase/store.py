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
      CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
      CREATE INDEX IF NOT EXISTS idx_images_document ON images(document_id);
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
