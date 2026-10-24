from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from docqa.config import settings

SUPPORTED = {".pdf", ".docx", ".pptx", ".md", ".txt"}
STATE_PATH = settings.data_dir / "watch_state.json"
STATUS = {
    "enabled": settings.watch_enabled,
    "directory": str(settings.watch_dir),
    "state": "starting",
    "last_scan": None,
    "files_seen": 0,
    "indexed": 0,
    "current_file": None,
    "last_error": None,
}


def status() -> dict:
    return dict(STATUS)


def _load_state() -> dict[str, dict]:
    if not STATE_PATH.is_file():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict[str, dict]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


async def watch_directory(ingest: Callable[[Path], Awaitable[dict]], remove: Callable[[str], Awaitable[dict]]) -> None:
    settings.watch_dir.mkdir(parents=True, exist_ok=True)
    state = _load_state()
    STATUS.update(state="watching", last_error=None)
    try:
        while True:
            STATUS["last_scan"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            STATUS["state"] = "scanning"
            STATUS["last_error"] = None
            try:
                paths = sorted(path for path in settings.watch_dir.rglob("*") if path.is_file() and path.suffix.lower() in SUPPORTED)
                STATUS["files_seen"] = len(paths)
                for path in paths:
                    key = str(path.resolve())
                    STATUS["current_file"] = path.name
                    try:
                        content = await asyncio.to_thread(path.read_bytes)
                        digest = hashlib.sha256(content).hexdigest()
                        previous = state.get(key, {})
                        if previous.get("sha256") == digest:
                            continue
                        STATUS["state"] = "indexing"
                        result = await ingest(path)
                        old_id = previous.get("document_id")
                        if old_id and old_id != result.get("id") and not result.get("skipped"):
                            await remove(old_id)
                        state[key] = {"sha256": digest, "document_id": result.get("id"), "name": path.name}
                        _save_state(state)
                        if not result.get("skipped"):
                            STATUS["indexed"] += 1
                    except Exception as exc:
                        STATUS["last_error"] = f"{path.name}: {type(exc).__name__}"
                STATUS["state"] = "error" if STATUS["last_error"] else "watching"
            except Exception as exc:
                STATUS["last_error"] = type(exc).__name__
                STATUS["state"] = "error"
            finally:
                STATUS["current_file"] = None
            await asyncio.sleep(settings.watch_interval_seconds)
    except asyncio.CancelledError:
        STATUS["state"] = "stopped"
        raise
