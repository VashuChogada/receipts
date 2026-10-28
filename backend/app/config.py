"""Settings, all from the environment so compose.yaml is the one place they change."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "off", "false", "no", ""}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    static_dir: Path
    # MDY (US) or DMY: how an ambiguous 03/04/2026 on a receipt is read.
    date_order: str
    # ISO 4217 code for new receipts and for showing amounts.
    currency: str
    semantic_search: bool
    # Where the models live: bge-small for search, PP-OCRv6 under rapidocr/.
    model_cache: Path
    embed_model: str
    # Minutes the model helper (OCR + embeddings) stays up after its last use.
    model_idle_minutes: float
    # ONNX Runtime threads for the models; leave the rest of the CPU to others.
    model_threads: int
    # "rapidocr" (PP-OCRv6, Tesseract as the fallback) or "tesseract".
    ocr_engine: str
    ocr_enabled: bool
    # File a scan as soon as OCR finds its date and total; the rest wait in review.
    auto_file: bool
    session_days: int

    @property
    def receipts_dir(self) -> Path:
        return self.data_dir / "receipts"

    @property
    def inbox_dir(self) -> Path:
        return self.receipts_dir / "_inbox"

    @property
    def trash_dir(self) -> Path:
        return self.receipts_dir / "_trash"


def load() -> Settings:
    data_dir = Path(os.environ.get("DATA_DIR", "./data")).resolve()
    return Settings(
        data_dir=data_dir,
        db_path=Path(os.environ.get("DB_PATH", str(data_dir / "receipts.db"))),
        static_dir=Path(os.environ.get("STATIC_DIR", str(Path(__file__).resolve().parent.parent / "static"))),
        date_order=os.environ.get("DATE_ORDER", "MDY").upper(),
        currency=os.environ.get("CURRENCY", "USD").upper(),
        semantic_search=_flag("SEMANTIC_SEARCH", True),
        model_cache=Path(os.environ.get("MODEL_CACHE", str(data_dir / "models"))),
        embed_model=os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5"),
        model_idle_minutes=float(os.environ.get("MODEL_IDLE_MINUTES", "5")),
        model_threads=int(os.environ.get("MODEL_THREADS", "2")),
        ocr_engine=os.environ.get("OCR_ENGINE", "rapidocr").lower(),
        ocr_enabled=_flag("OCR_ENABLED", True),
        auto_file=_flag("AUTO_FILE", True),
        session_days=int(os.environ.get("SESSION_DAYS", "90")),
    )


settings = load()
