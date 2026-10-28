"""Uploads checked by their bytes, and small JPEG previews for lists and PDFs.

Previews live in data/cache/: regenerable, never part of the receipts folder.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from . import config, ocr, storage

MAX_UPLOAD = 25 * 1024 * 1024
PREVIEW_WIDTHS = (320, 1200)


def sniff(data: bytes) -> str | None:
    """The real type of an upload, whatever the browser claimed."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def _cache_dir() -> Path:
    path = config.settings.data_dir / "cache" / "previews"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _placeholder(width: int, label: str) -> Image.Image:
    img = Image.new("RGB", (width, round(width * 1.3)), "#e2e8f0")
    draw = ImageDraw.Draw(img)
    draw.text((width // 2 - 12, round(width * 0.62)), label, fill="#475569")
    return img


def preview(rel_path: str, mime: str, width: int) -> Path:
    width = min(PREVIEW_WIDTHS, key=lambda w: abs(w - width))
    src = storage.absolute(rel_path)
    stat = src.stat()
    out = _cache_dir() / f"{src.stem[-36:]}-{src.suffix[1:]}-{width}-{stat.st_mtime_ns}.jpg"
    if out.exists():
        return out
    if mime == "application/pdf":
        img = ocr.pdf_page_image(src, dpi=110 if width <= 320 else 150) or _placeholder(width, "PDF")
    else:
        with Image.open(src) as opened:
            img = ImageOps.exif_transpose(opened).convert("RGB")
    img = img.convert("RGB")
    img.thumbnail((width, width * 6), Image.LANCZOS)
    tmp = out.with_suffix(".tmp")
    img.save(tmp, "JPEG", quality=78, optimize=True, progressive=True)
    tmp.replace(out)
    return out
