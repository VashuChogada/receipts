"""The receipts folder, the source of truth:

    receipts/_inbox/<id>.jpg + <id>.json              until confirmed
    receipts/YYYY/MM/<Category>/YYYY-MM-DD_<Merchant>_<Amount>_<id>.jpg + .json
    receipts/_trash/...                               deleted, kept until cleared by hand

Paths in the database are relative to receipts/, with forward slashes.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from . import config

MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "application/pdf": ".pdf",
}


def root() -> Path:
    return config.settings.receipts_dir


def rel(path: Path) -> str:
    return path.resolve().relative_to(root().resolve()).as_posix()


def absolute(rel_path: str) -> Path:
    path = (root() / rel_path).resolve()
    # Never step outside the receipts folder, whatever a details file says.
    if root().resolve() not in path.parents and path != root().resolve():
        raise ValueError(f"path outside the receipts folder: {rel_path}")
    return path


def slug(text: str | None, maxlen: int = 40, fallback: str = "Unknown") -> str:
    text = (text or "").strip()
    text = re.sub(r"['’]", "", text)
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")
    return (text[:maxlen].rstrip("-") or fallback)


def ext_for(mime: str) -> str:
    return MIME_EXT.get(mime, ".bin")


def inbox_paths(receipt_id: str, ext: str) -> tuple[Path, Path]:
    folder = config.settings.inbox_dir
    return folder / f"{receipt_id}{ext}", folder / f"{receipt_id}.json"


def final_paths(
    receipt_id: str, ext: str, txn_date: str | None, merchant: str | None, total: float | None,
    category: str | None, fallback_date: str,
) -> tuple[Path, Path]:
    day = txn_date or fallback_date[:10]
    year, month = day[:4], day[5:7]
    amount = f"{total:.2f}" if total is not None else "0.00"
    base = f"{day}_{slug(merchant)}_{amount}_{receipt_id}"
    folder = root() / year / month / slug(category, fallback="Uncategorized")
    return folder / f"{base}{ext}", folder / f"{base}.json"


def attachment_path(main_file: Path, attachment_id: str, ext: str) -> Path:
    return main_file.with_name(f"{main_file.stem}_att-{attachment_id[:8]}{ext}")


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


def write_json(path: Path, data: dict) -> None:
    """Atomic: a crash mid-write leaves the old file, never half a new one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False, default=str)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def move(src: Path, dst: Path) -> None:
    if src.resolve() == dst.resolve():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    _prune_empty(src.parent)


def _prune_empty(folder: Path) -> None:
    """Remove folders a move left empty, up to receipts/ itself."""
    top = root().resolve()
    folder = folder.resolve()
    while folder != top and top in folder.parents:
        try:
            folder.rmdir()
        except OSError:
            return
        folder = folder.parent


def to_trash(rel_path: str) -> None:
    src = absolute(rel_path)
    if not src.exists():
        return
    dst = config.settings.trash_dir / rel_path.replace("_inbox/", "inbox/")
    if dst.exists():
        dst = dst.with_name(f"{dst.stem}.{os.getpid()}{dst.suffix}")
    move(src, dst)


def iter_sidecars():
    """Every details file outside _trash, for a reindex."""
    base = root()
    if not base.exists():
        return
    for path in sorted(base.rglob("*.json")):
        parts = path.relative_to(base).parts
        if parts and parts[0] == "_trash":
            continue
        if path.name.startswith(".tmp-"):
            continue
        yield path
