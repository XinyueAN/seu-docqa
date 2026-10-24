from __future__ import annotations

import uuid
from datetime import datetime, timezone

JOBS: dict[str, dict] = {}
TASKS: set = set()


def create_job(filename: str) -> dict:
    if len(JOBS) >= 500:
        finished = [key for key, item in JOBS.items() if item["status"] in {"completed", "failed"}]
        for key in finished[:250]:
            JOBS.pop(key, None)
    job_id = uuid.uuid4().hex
    item = {
        "id": job_id,
        "filename": filename,
        "status": "queued",
        "phase": "等待处理",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "result": None,
        "error": None,
    }
    JOBS[job_id] = item
    return dict(item)


def update_job(job_id: str | None, **changes) -> None:
    if job_id and job_id in JOBS:
        JOBS[job_id].update(changes)


def get_job(job_id: str) -> dict | None:
    item = JOBS.get(job_id)
    return dict(item) if item else None
