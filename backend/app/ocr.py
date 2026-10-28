"""Text from a receipt image or PDF, all local.

PP-OCRv6 (PaddleOCR's small model, through RapidOCR on ONNX Runtime) reads
photos of receipts better than Tesseract: on the first real scans it was
tried on, it got every amount right where Tesseract read $251.00 as $31.00. It runs in
the model helper process (modelhost.py). Tesseract stays as the fallback, and
a reading the parser can't get a total and a date from is tried with both.

The phone already straightened, cropped and boosted the image (frontend
lib/preprocess.ts); for Tesseract this only sizes it and evens the contrast.
"""

from __future__ import annotations

import logging
import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytesseract
from PIL import Image, ImageFilter, ImageOps

from . import config, parse

log = logging.getLogger(__name__)

# Tesseract reads receipt print best at roughly 300 dpi: an 80 mm slip about
# 1000 px wide. Phone shots are bigger, so mostly this scales down.
TARGET_WIDTH = 1400
MIN_CONFIDENCE = 60


@dataclass
class OcrResult:
    text: str
    confidence: float | None
    engine: str


def prepare(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img)
    img = img.convert("L")
    if img.width > TARGET_WIDTH * 1.4 or img.width < TARGET_WIDTH * 0.7:
        ratio = TARGET_WIDTH / img.width
        img = img.resize((TARGET_WIDTH, max(1, round(img.height * ratio))), Image.LANCZOS)
    img = ImageOps.autocontrast(img, cutoff=1)
    return img.filter(ImageFilter.SHARPEN)


def _run(img: Image.Image, psm: int) -> tuple[str, float | None]:
    data = pytesseract.image_to_data(
        img, lang="eng", config=f"--oem 1 --psm {psm} -c preserve_interword_spaces=1",
        output_type=pytesseract.Output.DICT,
    )
    lines: dict[tuple, list[str]] = {}
    confs = []
    for i, word in enumerate(data["text"]):
        word = word.strip()
        if not word:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(word)
        conf = float(data["conf"][i])
        if conf >= 0:
            confs.append(conf)
    text = "\n".join(" ".join(words) for _, words in sorted(lines.items()))
    return text, (round(sum(confs) / len(confs), 1) if confs else None)


def usefulness(text: str) -> int:
    """How much the parser gets out of a reading: the measure for choosing
    between page-segmentation modes, which confidence alone doesn't capture."""
    p = parse.parse_receipt(text)
    return (3 * (p.total is not None) + 2 * (p.txn_date is not None) + (p.subtotal is not None)
            + (p.tax is not None) + (p.merchant is not None) + min(len(p.line_items), 5))


def tesseract_available() -> bool:
    return bool(shutil.which("tesseract") or Path(pytesseract.pytesseract.tesseract_cmd).exists())


def lines_from_boxes(boxes: list, texts: list[str]) -> str:
    """Rebuild a receipt's lines from detected text boxes.

    A label and its amount are separate boxes far apart on one row, and a
    photo is rarely square to the slip, so rows are found after undoing the
    page's tilt (the median angle of the boxes' top edges). A box joins a row
    when its center is within half the smaller text height of the row's.
    """
    if not boxes:
        return ""
    angles = []
    for b in boxes:
        (x0, y0), (x1, y1) = b[0], b[1]
        if x1 - x0 > 2 * abs(y1 - y0):
            angles.append(math.atan2(y1 - y0, x1 - x0))
    theta = sorted(angles)[len(angles) // 2] if angles else 0.0
    cos_t, sin_t = math.cos(theta), math.sin(theta)

    items = []
    for b, t in zip(boxes, texts):
        cx = sum(p[0] for p in b) / 4
        cy = sum(p[1] for p in b) / 4
        h = (math.dist(b[0], b[3]) + math.dist(b[1], b[2])) / 2
        x = cx * cos_t + cy * sin_t
        y = -cx * sin_t + cy * cos_t
        items.append((y, max(h, 1.0), x, t))
    items.sort()

    rows: list[dict] = []
    for y, h, x, t in items:
        # Only the last few rows can match: items arrive top to bottom.
        for row in reversed(rows[-3:]):
            if abs(y - row["y"]) <= 0.5 * min(h, row["h"]):
                row["items"].append((x, t))
                n = len(row["items"])
                row["y"] += (y - row["y"]) / n
                row["h"] += (h - row["h"]) / n
                break
        else:
            rows.append({"y": y, "h": h, "items": [(x, t)]})
    rows.sort(key=lambda r: r["y"])
    return "\n".join(" ".join(t for _, t in sorted(r["items"])) for r in rows)


def ocr_rapid(path: Path) -> OcrResult:
    from .modelhost import host

    out = host.call("ocr", str(path))
    scores = out["scores"]
    conf = round(100 * sum(scores) / len(scores), 1) if scores else None
    return OcrResult(text=lines_from_boxes(out["boxes"], out["texts"]), confidence=conf, engine="PP-OCRv6 small")


def ocr_image(img: Image.Image) -> OcrResult:
    prepared = prepare(img)
    # psm 6 reads a uniform block row by row, which keeps a receipt's label
    # and its right-aligned amount on one line. psm 4 (one column of variable
    # text) is the fallback for slips where that goes wrong.
    text, conf = _run(prepared, 6)
    score = usefulness(text)
    if score < 6 or (conf or 0) < MIN_CONFIDENCE:
        text4, conf4 = _run(prepared, 4)
        score4 = usefulness(text4)
        if score4 > score or (score4 == score and (conf4 or 0) > (conf or 0)):
            text, conf = text4, conf4
    return OcrResult(text=text, confidence=conf, engine=f"tesseract {pytesseract.get_tesseract_version()}")


def pdf_text(path: Path) -> str | None:
    """The PDF's own text layer, when it has one (emailed receipts do)."""
    if not shutil.which("pdftotext"):
        return None
    try:
        out = subprocess.run(
            ["pdftotext", "-layout", "-f", "1", "-l", "3", str(path), "-"],
            capture_output=True, timeout=60, check=True,
        ).stdout.decode("utf-8", "replace")
    except (subprocess.SubprocessError, OSError) as exc:
        log.warning("pdftotext failed on %s: %s", path.name, exc)
        return None
    return out if sum(c.isalnum() for c in out) >= 20 else None


def pdf_page_image(path: Path, dpi: int = 200) -> Image.Image | None:
    """Page 1 as an image, for OCR of scanned PDFs and for previews."""
    if not shutil.which("pdftoppm"):
        return None
    with tempfile.TemporaryDirectory() as tmp:
        prefix = Path(tmp) / "page"
        try:
            subprocess.run(
                ["pdftoppm", "-r", str(dpi), "-f", "1", "-l", "1", "-png", "-singlefile", str(path), str(prefix)],
                capture_output=True, timeout=120, check=True,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            log.warning("pdftoppm failed on %s: %s", path.name, exc)
            return None
        png = prefix.with_suffix(".png")
        if not png.exists():
            return None
        with Image.open(png) as img:
            img.load()
            return img.copy()


def extract(path: Path, mime: str) -> OcrResult:
    if mime == "application/pdf":
        text = pdf_text(path)
        if text:
            return OcrResult(text=text, confidence=100.0, engine="pdftotext")
        page = pdf_page_image(path, dpi=300)
        if page is None:
            raise RuntimeError("Can't read this PDF: it has no text layer and poppler isn't installed")
        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / "page.png"
            page.save(png)
            return _read(png, page)
    with Image.open(path) as img:
        img.load()
        return _read(path, img)


def _read(path: Path, img: Image.Image) -> OcrResult:
    results: list[OcrResult] = []
    if config.settings.ocr_engine == "rapidocr":
        try:
            results.append(ocr_rapid(path))
        except Exception as exc:  # noqa: BLE001 - Tesseract still works
            log.warning("PP-OCRv6 failed, falling back to Tesseract: %s", exc)
    if tesseract_available() and (not results or usefulness(results[0].text) < 6):
        results.append(ocr_image(img))
    if not results:
        raise RuntimeError("No OCR engine is available")
    return max(results, key=lambda r: (usefulness(r.text), r.confidence or 0))
