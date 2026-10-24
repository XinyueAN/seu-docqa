from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT_DIR / ".env")
except ImportError:
    pass


def _read_api_key() -> str:
    """Read the key without ever including it in diagnostics or logs."""
    value = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if value:
        return value
    key_file = ROOT_DIR / "deepseek-api-keys.txt"
    if key_file.is_file():
        for line in key_file.read_text(encoding="utf-8").splitlines():
            candidate = line.strip().strip('"').strip("'")
            if candidate and not candidate.startswith("#"):
                if "=" in candidate and candidate.split("=", 1)[0].strip().upper() in {"DEEPSEEK_API_KEY", "API_KEY"}:
                    candidate = candidate.split("=", 1)[1].strip().strip('"').strip("'")
                return candidate
    return ""


@dataclass(frozen=True)
class Settings:
    model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
    base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    data_dir: Path = Path(os.getenv("DATA_DIR", str(ROOT_DIR / "data"))).resolve()
    watch_dir: Path = Path(os.getenv("WATCH_DIR", str(Path(os.getenv("DATA_DIR", str(ROOT_DIR / "data"))) / "watch"))).resolve()
    watch_interval_seconds: int = max(10, int(os.getenv("WATCH_INTERVAL_SECONDS", "30")))
    watch_enabled: bool = os.getenv("WATCH_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = int(os.getenv("PORT", "8000"))
    vision_max_images: int = int(os.getenv("VISION_MAX_IMAGES", "12"))
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
    reranker_model: str = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
    enable_local_embedding: bool = os.getenv("ENABLE_LOCAL_EMBEDDING", "false").lower() in {"1", "true", "yes", "on"}
    enable_local_reranker: bool = os.getenv("ENABLE_LOCAL_RERANKER", "false").lower() in {"1", "true", "yes", "on"}

    @property
    def api_key(self) -> str:
        return _read_api_key()


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
