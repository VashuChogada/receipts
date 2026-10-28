"""Receipts as records: create, read, edit, file away, delete, rebuild.

Every write ends the same way: the database row is updated, the files are
moved to where the record says they belong, the search index is refreshed and
the details file is rewritten. The details file is complete on its own, so
`reindex` can rebuild every table from the folder.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from . import categorize, config, merchants, storage
from .db import Conn

log = logging.getLogger(__name__)

SCHEMA = 1
FIELDS = [
    "merchant", "txn_date", "txn_time", "subtotal", "tax", "total",
    "payment_method", "card_last4", "category", "notes",
]
TYPED = {
    "hsa": ["patient", "provider", "eligible_amount", "reimbursed", "reimbursed_date", "claim_ref"],
    "donation": ["organization", "ein", "donation_type", "deductible_amount", "items_description", "acknowledgment"],
    "warranty": ["product", "serial", "expires_on"],
}
BOOL_FIELDS = {"reimbursed", "acknowledgment"}
# A single gift this size needs the charity's written acknowledgment (IRS Pub. 1771).
DONATION_ACK_THRESHOLD = 250.0


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class NotFound(Exception):
    pass


# --- reading -----------------------------------------------------------------


def _typed_kinds(conn: sqlite3.Connection, tag_names: list[str]) -> set[str]:
    if not tag_names:
        return set()
    marks = ",".join("?" * len(tag_names))
    rows = conn.execute(f"SELECT kind FROM tags WHERE name IN ({marks})", tag_names).fetchall()
    return {r[0] for r in rows if r[0] != "plain"}


def get(conn: sqlite3.Connection, receipt_id: str) -> dict:
    row = conn.execute("SELECT * FROM receipts WHERE id = ?", (receipt_id,)).fetchone()
    if not row:
        raise NotFound(receipt_id)
    rec = dict(row)
    rec["tags"] = [r[0] for r in conn.execute(
        "SELECT tag FROM receipt_tags WHERE receipt_id = ? ORDER BY tag", (receipt_id,)
    )]
    for kind, cols in TYPED.items():
        t = conn.execute(f"SELECT {', '.join(cols)} FROM {kind} WHERE receipt_id = ?", (receipt_id,)).fetchone()
        rec[kind] = {c: (bool(t[c]) if c in BOOL_FIELDS else t[c]) for c in cols} if t else None
    rec["line_items"] = [dict(r) for r in conn.execute(
        "SELECT description, qty, unit_price, amount FROM line_items WHERE receipt_id = ? ORDER BY position",
        (receipt_id,),
    )]
    rec["attachments"] = [dict(r) for r in conn.execute(
        "SELECT id, file_path, mime, original_name, label, created_at FROM attachments WHERE receipt_id = ? "
        "ORDER BY created_at", (receipt_id,),
    )]
    rec["history"] = json.loads(rec.pop("history_json") or "[]")
    rec["parsed"] = json.loads(rec.pop("parsed_json") or "null")
    rec["suggested_tags"] = json.loads(rec["suggested_tags"] or "[]")
    rec["kinds"] = sorted(_typed_kinds(conn, rec["tags"]))
    rec["needs_acknowledgment"] = needs_acknowledgment(rec)
    rec.pop("embed_hash", None)
    return rec


def needs_acknowledgment(rec: dict) -> bool:
    if "donation" not in rec.get("kinds", []):
        return False
    d = rec.get("donation") or {}
    amount = d.get("deductible_amount") or rec.get("total") or 0
    has_letter = d.get("acknowledgment") or any(
        (a.get("label") or "").lower().startswith("ack") for a in rec.get("attachments", [])
    )
    return amount >= DONATION_ACK_THRESHOLD and not has_letter


def summary(rec: dict) -> dict:
    """The fields a list row needs."""
    keys = ["id", "status", "merchant", "txn_date", "txn_time", "total", "tax", "category", "payment_method",
            "card_last4", "tags", "mime", "created_by", "created_at", "needs_acknowledgment", "ocr_confidence", "error"]
    out = {k: rec.get(k) for k in keys}
    if rec.get("hsa"):
        out["reimbursed"] = rec["hsa"].get("reimbursed")
    return out


def to_sidecar(rec: dict) -> dict:
    file_name = Path(rec["file_path"]).name
    return {
        "schema": SCHEMA,
        "id": rec["id"],
        "status": rec["status"],
        **{f: rec.get(f) for f in FIELDS},
        "currency": rec.get("currency") or config.settings.currency,
        "merchant_raw": rec.get("merchant_raw"),
        "tags": rec.get("tags", []),
        "hsa": rec.get("hsa"),
        "donation": rec.get("donation"),
        "warranty": rec.get("warranty"),
        "line_items": rec.get("line_items", []),
        "file": file_name,
        "mime": rec["mime"],
        "original_name": rec.get("original_name"),
        "attachments": [
            {k: a[k] for k in ("id", "mime", "original_name", "label", "created_at")} | {"file": Path(a["file_path"]).name}
            for a in rec.get("attachments", [])
        ],
        "ocr": {
            "text": rec.get("raw_text"),
            "confidence": rec.get("ocr_confidence"),
            "parsed": rec.get("parsed"),
            "suggested_tags": rec.get("suggested_tags", []),
            "error": rec.get("error"),
        },
        "created_by": rec.get("created_by"),
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "confirmed_at": rec.get("confirmed_at"),
        "history": rec.get("history", []),
    }


def save_sidecar(conn: sqlite3.Connection, receipt_id: str) -> None:
    rec = get(conn, receipt_id)
    storage.write_json(storage.absolute(rec["sidecar_path"]), to_sidecar(rec))


# --- search index ------------------------------------------------------------


def index_text(rec: dict) -> tuple[str, str]:
    merchant = " ".join(x for x in (rec.get("merchant"), rec.get("merchant_raw")) if x)
    parts = [
        rec.get("category") or "",
        " ".join(rec.get("tags", [])),
        " ".join(i["description"] for i in rec.get("line_items", [])),
        rec.get("notes") or "",
        rec.get("payment_method") or "",
    ]
    for kind in TYPED:
        if rec.get(kind):
            parts.extend(str(v) for v in rec[kind].values() if isinstance(v, str))
    parts.append(rec.get("raw_text") or "")
    return merchant, "\n".join(p for p in parts if p)


def embed_source(rec: dict) -> str:
    """What the embedding model reads: the meaning-bearing fields first, then
    the start of the receipt text."""
    bits = [
        rec.get("merchant") or "",
        rec.get("category") or "",
        ", ".join(rec.get("tags", [])),
        ", ".join(i["description"] for i in rec.get("line_items", [])[:20]),
        rec.get("notes") or "",
        (rec.get("raw_text") or "")[:400],
    ]
    return ". ".join(b for b in bits if b)


def reindex_one(conn: sqlite3.Connection, receipt_id: str) -> None:
    rec = get(conn, receipt_id)
    merchant, body = index_text(rec)
    seq = rec["seq"]
    conn.execute("DELETE FROM receipts_fts WHERE rowid = ?", (seq,))
    conn.execute("DELETE FROM receipts_tri WHERE rowid = ?", (seq,))
    conn.execute("INSERT INTO receipts_fts (rowid, merchant, body) VALUES (?, ?, ?)", (seq, merchant, body))
    conn.execute("INSERT INTO receipts_tri (rowid, merchant, body) VALUES (?, ?, ?)", (seq, merchant, body))


def embedding_due(conn: Conn, receipt_id: str) -> tuple[int, str, str] | None:
    """(seq, text, hash) when the stored embedding is missing or stale."""
    if not conn.vec_enabled:
        return None
    rec = get(conn, receipt_id)
    text = embed_source(rec)
    digest = hashlib.sha1(text.encode()).hexdigest()
    stored = conn.execute("SELECT embed_hash FROM receipts WHERE id = ?", (receipt_id,)).fetchone()[0]
    if stored == digest:
        return None
    return rec["seq"], text, digest


def store_embedding(conn: Conn, seq: int, vector: list[float], digest: str) -> None:
    import sqlite_vec

    conn.execute("DELETE FROM receipts_vec WHERE rowid = ?", (seq,))
    conn.execute("INSERT INTO receipts_vec (rowid, embedding) VALUES (?, ?)", (seq, sqlite_vec.serialize_float32(vector)))
    conn.execute("UPDATE receipts SET embed_hash = ? WHERE seq = ?", (digest, seq))


# --- writing -----------------------------------------------------------------


def _finish(conn: sqlite3.Connection, receipt_id: str) -> dict:
    relocate(conn, receipt_id)
    reindex_one(conn, receipt_id)
    save_sidecar(conn, receipt_id)
    conn.commit()
    return get(conn, receipt_id)


def create(
    conn: sqlite3.Connection, data: bytes, mime: str, original_name: str | None, user: str | None,
    tags: list[str] | None = None,
) -> str:
    receipt_id = str(uuid.uuid4())
    file_path, sidecar_path = storage.inbox_paths(receipt_id, storage.ext_for(mime))
    storage.write_bytes(file_path, data)
    stamp = now()
    conn.execute(
        "INSERT INTO receipts (id, status, currency, file_path, sidecar_path, mime, original_name, created_by, created_at, updated_at) "
        "VALUES (?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?)",
        (receipt_id, config.settings.currency, storage.rel(file_path), storage.rel(sidecar_path), mime, original_name, user, stamp, stamp),
    )
    # Tags picked at scan time ("this one's HSA").
    conn.executemany(
        "INSERT INTO receipt_tags (receipt_id, tag) VALUES (?, ?)", [(receipt_id, t) for t in _ensure_tags(conn, tags or [])]
    )
    _finish(conn, receipt_id)
    return receipt_id


def set_status(conn: sqlite3.Connection, receipt_id: str, status: str, error: str | None = None) -> None:
    conn.execute(
        "UPDATE receipts SET status = ?, error = ?, updated_at = ? WHERE id = ?", (status, error, now(), receipt_id)
    )
    conn.commit()


def apply_ocr(
    conn: sqlite3.Connection,
    receipt_id: str,
    text: str,
    confidence: float | None,
    parsed: dict,
    rules: list[categorize.Rule],
    overwrite: bool = False,
) -> dict:
    """Fill fields from OCR. Fields the user already set stay, unless overwrite
    (a deliberate reprocess)."""
    rec = get(conn, receipt_id)
    raw_merchant = parsed.get("merchant")
    resolved = {
        "merchant": merchants.resolve(conn, raw_merchant),
        "txn_date": parsed.get("txn_date"),
        "txn_time": parsed.get("txn_time"),
        "subtotal": parsed.get("subtotal"),
        "tax": parsed.get("tax"),
        "total": parsed.get("total"),
        "payment_method": parsed.get("payment_method"),
        "card_last4": parsed.get("card_last4"),
    }
    category, suggested, _ = categorize.classify(rules, resolved["merchant"] or raw_merchant, text)
    resolved["category"] = category or "Other"

    sets, values = [], []
    for f, v in resolved.items():
        if v is None:
            continue
        if overwrite or rec.get(f) in (None, ""):
            sets.append(f"{f} = ?")
            values.append(v)
    status = rec["status"] if rec["status"] == "confirmed" else "review"
    sets += ["merchant_raw = ?", "raw_text = ?", "ocr_confidence = ?", "parsed_json = ?", "suggested_tags = ?",
             "status = ?", "error = NULL", "updated_at = ?"]
    values += [raw_merchant, text, confidence, json.dumps(parsed), json.dumps(suggested), status, now()]
    conn.execute(f"UPDATE receipts SET {', '.join(sets)} WHERE id = ?", (*values, receipt_id))

    if overwrite or not rec["line_items"]:
        _replace_line_items(conn, receipt_id, parsed.get("line_items") or [])
    return _finish(conn, receipt_id)


def _replace_line_items(conn: sqlite3.Connection, receipt_id: str, items: list[dict]) -> None:
    conn.execute("DELETE FROM line_items WHERE receipt_id = ?", (receipt_id,))
    conn.executemany(
        "INSERT INTO line_items (receipt_id, position, description, qty, unit_price, amount) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (receipt_id, i, str(it.get("description", ""))[:200], it.get("qty"), it.get("unit_price"), it.get("amount"))
            for i, it in enumerate(items)
            if str(it.get("description", "")).strip()
        ],
    )


def _ensure_tags(conn: sqlite3.Connection, names: list[str]) -> list[str]:
    out = []
    for name in names:
        name = name.strip()[:40]
        if not name:
            continue
        row = conn.execute("SELECT name FROM tags WHERE name = ?", (name,)).fetchone()
        if row:
            out.append(row[0])
        else:
            conn.execute("INSERT INTO tags (name, kind, color) VALUES (?, 'plain', '#64748b')", (name,))
            out.append(name)
    return sorted(set(out), key=str.lower)


def _clean_value(field: str, value):
    if value == "":
        return None
    if field in {"subtotal", "tax", "total", "eligible_amount", "deductible_amount"} and value is not None:
        return round(float(value), 2)
    if field in {"txn_date", "reimbursed_date", "expires_on"} and value is not None:
        return date.fromisoformat(str(value)[:10]).isoformat()
    if field in BOOL_FIELDS:
        return 1 if value else 0
    if isinstance(value, str):
        return value.strip()
    return value


def update(
    conn: sqlite3.Connection,
    receipt_id: str,
    patch: dict,
    user: str | None,
    remember_category: bool = False,
) -> dict:
    old = get(conn, receipt_id)
    changes: dict[str, list] = {}

    sets, values = [], []
    for f in FIELDS:
        if f in patch:
            new = _clean_value(f, patch[f])
            if new != old.get(f):
                changes[f] = [old.get(f), new]
                sets.append(f"{f} = ?")
                values.append(new)

    if "tags" in patch and patch["tags"] is not None:
        tags = _ensure_tags(conn, list(patch["tags"]))
        if tags != old["tags"]:
            changes["tags"] = [old["tags"], tags]
            conn.execute("DELETE FROM receipt_tags WHERE receipt_id = ?", (receipt_id,))
            conn.executemany("INSERT INTO receipt_tags (receipt_id, tag) VALUES (?, ?)", [(receipt_id, t) for t in tags])

    for kind, cols in TYPED.items():
        data = patch.get(kind)
        if not isinstance(data, dict):
            continue
        merged = {c: _clean_value(c, data.get(c, (old.get(kind) or {}).get(c))) for c in cols}
        before = {c: (_clean_value(c, v) if c in BOOL_FIELDS else v) for c, v in (old.get(kind) or {}).items()}
        if merged != before:
            changes[kind] = [old.get(kind), {c: (bool(v) if c in BOOL_FIELDS else v) for c, v in merged.items()}]
            conn.execute(
                f"INSERT INTO {kind} (receipt_id, {', '.join(cols)}) VALUES (?, {', '.join('?' * len(cols))}) "
                f"ON CONFLICT(receipt_id) DO UPDATE SET {', '.join(f'{c} = excluded.{c}' for c in cols)}",
                (receipt_id, *merged.values()),
            )

    if "line_items" in patch and patch["line_items"] is not None:
        if patch["line_items"] != old["line_items"]:
            changes["line_items"] = [len(old["line_items"]), len(patch["line_items"])]
            _replace_line_items(conn, receipt_id, patch["line_items"])

    status = patch.get("status")
    if status and status != old["status"]:
        if status not in ("review", "confirmed"):
            raise ValueError(f"can't set status to {status}")
        changes["status"] = [old["status"], status]
        sets.append("status = ?")
        values.append(status)
        if status == "confirmed":
            sets.append("confirmed_at = ?")
            values.append(now())

    if sets:
        conn.execute(f"UPDATE receipts SET {', '.join(sets)} WHERE id = ?", (*values, receipt_id))

    if changes:
        history = old["history"] + [{"at": now(), "by": user, "changes": changes}]
        conn.execute(
            "UPDATE receipts SET history_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(history, default=str), now(), receipt_id),
        )

    current = get(conn, receipt_id)
    if current["status"] == "confirmed":
        merchants.learn(conn, current.get("merchant_raw"), current.get("merchant"))
    if remember_category and current.get("merchant") and current.get("category"):
        categorize.remember_merchant(conn, current["merchant"], current["category"])
    return _finish(conn, receipt_id)


def relocate(conn: sqlite3.Connection, receipt_id: str) -> None:
    """Move the files to where the record says they belong: the inbox until
    confirmed, then YYYY/MM/<Category>/ under a name built from the fields."""
    rec = get(conn, receipt_id)
    ext = Path(rec["file_path"]).suffix
    if rec["status"] == "confirmed":
        new_file, new_sidecar = storage.final_paths(
            receipt_id, ext, rec["txn_date"], rec["merchant"], rec["total"], rec["category"], rec["created_at"]
        )
    else:
        new_file, new_sidecar = storage.inbox_paths(receipt_id, ext)
    old_file = storage.absolute(rec["file_path"])
    if old_file.resolve() == new_file.resolve():
        return
    old_sidecar = storage.absolute(rec["sidecar_path"])
    storage.move(old_file, new_file)
    if old_sidecar.exists():
        storage.move(old_sidecar, new_sidecar)
    for a in rec["attachments"]:
        src = storage.absolute(a["file_path"])
        dst = storage.attachment_path(new_file, a["id"], src.suffix)
        if src.exists():
            storage.move(src, dst)
        conn.execute("UPDATE attachments SET file_path = ? WHERE id = ?", (storage.rel(dst), a["id"]))
    conn.execute(
        "UPDATE receipts SET file_path = ?, sidecar_path = ? WHERE id = ?",
        (storage.rel(new_file), storage.rel(new_sidecar), receipt_id),
    )


def add_attachment(
    conn: sqlite3.Connection, receipt_id: str, data: bytes, mime: str, original_name: str | None,
    label: str | None, user: str | None,
) -> dict:
    rec = get(conn, receipt_id)
    attachment_id = str(uuid.uuid4())
    path = storage.attachment_path(storage.absolute(rec["file_path"]), attachment_id, storage.ext_for(mime))
    storage.write_bytes(path, data)
    conn.execute(
        "INSERT INTO attachments (id, receipt_id, file_path, mime, original_name, label, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (attachment_id, receipt_id, storage.rel(path), mime, original_name, label, now()),
    )
    history = rec["history"] + [{"at": now(), "by": user, "changes": {"attachment": [None, label or original_name]}}]
    conn.execute("UPDATE receipts SET history_json = ?, updated_at = ? WHERE id = ?",
                 (json.dumps(history), now(), receipt_id))
    return _finish(conn, receipt_id)


def delete_attachment(conn: sqlite3.Connection, receipt_id: str, attachment_id: str) -> dict:
    row = conn.execute(
        "SELECT file_path FROM attachments WHERE id = ? AND receipt_id = ?", (attachment_id, receipt_id)
    ).fetchone()
    if not row:
        raise NotFound(attachment_id)
    storage.to_trash(row[0])
    conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
    return _finish(conn, receipt_id)


def delete(conn: Conn, receipt_id: str) -> None:
    rec = get(conn, receipt_id)
    for a in rec["attachments"]:
        storage.to_trash(a["file_path"])
    storage.to_trash(rec["file_path"])
    storage.to_trash(rec["sidecar_path"])
    seq = rec["seq"]
    conn.execute("DELETE FROM receipts_fts WHERE rowid = ?", (seq,))
    conn.execute("DELETE FROM receipts_tri WHERE rowid = ?", (seq,))
    if conn.vec_enabled:
        conn.execute("DELETE FROM receipts_vec WHERE rowid = ?", (seq,))
    conn.execute("DELETE FROM receipts WHERE id = ?", (receipt_id,))
    conn.commit()


# --- rebuilding from the folder ----------------------------------------------


def import_sidecar(conn: sqlite3.Connection, path: Path) -> str | None:
    """Insert one details file's record. The file sits beside it."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("skipping unreadable %s: %s", path, exc)
        return None
    if not isinstance(data, dict) or "id" not in data or "file" not in data:
        return None
    file_path = path.with_name(data["file"])
    if not file_path.exists():
        log.warning("skipping %s: its file %s is missing", path, file_path.name)
        return None
    rid = data["id"]
    ocr = data.get("ocr") or {}
    status = data.get("status", "review")
    if status == "processing":
        status = "queued"
    conn.execute("DELETE FROM receipts WHERE id = ?", (rid,))
    conn.execute(
        f"INSERT INTO receipts (id, status, {', '.join(FIELDS)}, currency, merchant_raw, file_path, sidecar_path, mime, "
        "original_name, raw_text, ocr_confidence, parsed_json, suggested_tags, error, created_by, created_at, updated_at, "
        f"confirmed_at, history_json) VALUES ({', '.join('?' * (len(FIELDS) + 18))})",
        (
            rid, status, *[data.get(f) for f in FIELDS], data.get("currency") or config.settings.currency, data.get("merchant_raw"),
            storage.rel(file_path), storage.rel(path), data.get("mime", "image/jpeg"), data.get("original_name"),
            ocr.get("text"), ocr.get("confidence"), json.dumps(ocr.get("parsed")),
            json.dumps(ocr.get("suggested_tags") or []), ocr.get("error"), data.get("created_by"),
            data.get("created_at") or now(), data.get("updated_at") or now(), data.get("confirmed_at"),
            json.dumps(data.get("history") or []),
        ),
    )
    tags = _ensure_tags(conn, data.get("tags") or [])
    conn.executemany("INSERT INTO receipt_tags (receipt_id, tag) VALUES (?, ?)", [(rid, t) for t in tags])
    for kind, cols in TYPED.items():
        typed = data.get(kind)
        if isinstance(typed, dict):
            conn.execute(
                f"INSERT INTO {kind} (receipt_id, {', '.join(cols)}) VALUES (?, {', '.join('?' * len(cols))})",
                (rid, *[_clean_value(c, typed.get(c)) for c in cols]),
            )
    _replace_line_items(conn, rid, data.get("line_items") or [])
    for a in data.get("attachments") or []:
        apath = path.with_name(a.get("file", ""))
        if a.get("id") and apath.exists():
            conn.execute(
                "INSERT INTO attachments (id, receipt_id, file_path, mime, original_name, label, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (a["id"], rid, storage.rel(apath), a.get("mime", "application/octet-stream"), a.get("original_name"),
                 a.get("label"), a.get("created_at") or now()),
            )
    reindex_one(conn, rid)
    return rid


def reindex_all(conn: Conn) -> int:
    """Rebuild every receipt table from the details files."""
    conn.execute("DELETE FROM receipts")
    conn.execute("DELETE FROM receipts_fts")
    conn.execute("DELETE FROM receipts_tri")
    if conn.vec_enabled:
        conn.execute("DELETE FROM receipts_vec")
    count = 0
    for path in storage.iter_sidecars():
        if import_sidecar(conn, path):
            count += 1
    conn.commit()
    log.info("reindexed %d receipts", count)
    return count
