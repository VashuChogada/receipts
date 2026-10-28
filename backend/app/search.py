"""Finding receipts: structured filters, then hybrid text ranking.

Free text goes through up to four channels, fused with Reciprocal Rank Fusion
(score = sum of 1 / (60 + rank) over the channels a receipt shows up in):

    words     FTS5 with Porter stemming: "groceries" finds "grocery"
    fuzzy     trigram FTS5 candidates re-scored with rapidfuzz: "starbcks"
    merchant  fuzzy match against known merchant names
    meaning   bge-small embeddings in sqlite-vec: "coffee" finds a latte
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from . import merchants as merchant_mod
from . import records
from .db import Conn
from .embed import embedder

log = logging.getLogger(__name__)

RRF_K = 60
CHANNEL_LIMIT = 200
# Cosine distance (1 - similarity). bge-small puts unrelated text around
# 0.45-0.6 from a query; the right receipt lands near 0.3-0.42 (calibrated
# in tests/test_semantic.py).
VECTOR_MAX_DISTANCE = 0.45
VECTOR_SPREAD = 0.05


@dataclass
class Filters:
    date_from: str | None = None
    date_to: str | None = None
    min_total: float | None = None
    max_total: float | None = None
    merchant: str | None = None
    category: str | None = None
    tags: list[str] = field(default_factory=list)
    payment_method: str | None = None
    card_last4: str | None = None
    status: str | None = None
    created_by: str | None = None
    reimbursed: bool | None = None


def where(f: Filters) -> tuple[str, list]:
    conds, params = [], []

    def add(sql: str, *values) -> None:
        conds.append(sql)
        params.extend(values)

    if f.status:
        add("r.status = ?", f.status)
    if f.date_from:
        add("r.txn_date >= ?", f.date_from)
    if f.date_to:
        add("r.txn_date <= ?", f.date_to)
    if f.min_total is not None:
        add("r.total >= ?", f.min_total)
    if f.max_total is not None:
        add("r.total <= ?", f.max_total)
    if f.merchant:
        add("r.merchant = ? COLLATE NOCASE", f.merchant)
    if f.category:
        add("r.category = ? COLLATE NOCASE", f.category)
    for tag in f.tags:
        add("EXISTS (SELECT 1 FROM receipt_tags t WHERE t.receipt_id = r.id AND t.tag = ? COLLATE NOCASE)", tag)
    if f.payment_method:
        add("r.payment_method = ? COLLATE NOCASE", f.payment_method)
    if f.card_last4:
        add("r.card_last4 = ?", f.card_last4)
    if f.created_by:
        add("r.created_by = ? COLLATE NOCASE", f.created_by)
    if f.reimbursed is True:
        add("EXISTS (SELECT 1 FROM hsa h WHERE h.receipt_id = r.id AND h.reimbursed = 1)")
    elif f.reimbursed is False:
        add("NOT EXISTS (SELECT 1 FROM hsa h WHERE h.receipt_id = r.id AND h.reimbursed = 1)")
    return (" AND ".join(conds) or "1"), params


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[\w']+", text.lower()) if len(t) >= 2]


def _fts_quote(token: str) -> str:
    return '"' + token.replace('"', '""') + '"'


def _channel_words(conn: sqlite3.Connection, tokens: list[str]) -> list[int]:
    if not tokens:
        return []
    query = " OR ".join(_fts_quote(t) + "*" for t in tokens)
    rows = conn.execute(
        "SELECT rowid FROM receipts_fts WHERE receipts_fts MATCH ? ORDER BY bm25(receipts_fts, 5.0, 1.0) LIMIT ?",
        (query, CHANNEL_LIMIT),
    ).fetchall()
    return [r[0] for r in rows]


def _channel_fuzzy(conn: sqlite3.Connection, tokens: list[str]) -> list[int]:
    long_tokens = [t for t in tokens if len(t) >= 4]
    if not long_tokens:
        return []
    grams = sorted({t[i : i + 3] for t in long_tokens for i in range(len(t) - 2)})
    query = " OR ".join(_fts_quote(g) for g in grams)
    rows = conn.execute(
        "SELECT rowid, lower(merchant), lower(body) FROM receipts_tri WHERE receipts_tri MATCH ? "
        "ORDER BY bm25(receipts_tri, 3.0, 1.0) LIMIT ?",
        (query, CHANNEL_LIMIT),
    ).fetchall()
    scored = []
    for seq, merchant, body in rows:
        words = set(re.findall(r"[\w']+", f"{merchant or ''} {body or ''}"))
        best = 0.0
        for t in long_tokens:
            # Whole words only: "coffee" mustn't match half of "toffee bar".
            best = max(best, max((fuzz.ratio(t, w) for w in words if abs(len(w) - len(t)) <= 2), default=0))
        if best >= 80:
            scored.append((best, seq))
    scored.sort(reverse=True)
    return [seq for _, seq in scored]


def _channel_merchant(conn: sqlite3.Connection, text: str) -> list[int]:
    names = [r[0] for r in conn.execute("SELECT DISTINCT merchant FROM receipts WHERE merchant IS NOT NULL")]
    matches = merchant_mod.fuzzy_find(text, names, cutoff=85)
    seqs: list[int] = []
    for name, _ in matches:
        seqs += [r[0] for r in conn.execute(
            "SELECT seq FROM receipts WHERE merchant = ? ORDER BY txn_date DESC LIMIT ?", (name, CHANNEL_LIMIT)
        )]
    return seqs


def _channel_meaning(conn: Conn, text: str) -> tuple[list[int], bool]:
    if not (conn.vec_enabled and embedder.enabled) or len(text.strip()) < 3:
        return [], False
    vector = embedder.query(text)
    if vector is None:
        return [], False
    import sqlite_vec

    rows = conn.execute(
        "SELECT rowid, distance FROM receipts_vec WHERE embedding MATCH ? AND k = ? ORDER BY distance",
        (sqlite_vec.serialize_float32(vector), 50),
    ).fetchall()
    if not rows:
        return [], True
    best = rows[0][1]
    keep = [seq for seq, dist in rows if dist <= VECTOR_MAX_DISTANCE and dist <= best + VECTOR_SPREAD]
    return keep, True


def rank(conn: Conn, text: str) -> tuple[dict[int, float], dict]:
    """seq -> fused score, plus which channels ran (for the UI and tests)."""
    tokens = _tokens(text)
    channels = {
        "words": (_channel_words(conn, tokens), 1.0),
        "fuzzy": (_channel_fuzzy(conn, tokens), 1.0),
        "merchant": (_channel_merchant(conn, text), 1.0),
    }
    meaning, ran = _channel_meaning(conn, text)
    channels["meaning"] = (meaning, 0.9)
    scores: dict[int, float] = {}
    for seqs, weight in channels.values():
        seen = set()
        for i, seq in enumerate(seqs):
            if seq in seen:
                continue
            seen.add(seq)
            scores[seq] = scores.get(seq, 0.0) + weight / (RRF_K + i + 1)
    info = {name: len(seqs) for name, (seqs, _) in channels.items()}
    info["meaning_ran"] = ran
    return scores, info


SORTS = {
    "date": "r.txn_date IS NULL, r.txn_date DESC, r.created_at DESC",
    "date_asc": "r.txn_date IS NULL, r.txn_date ASC, r.created_at ASC",
    "amount": "r.total IS NULL, r.total DESC",
    "amount_asc": "r.total IS NULL, r.total ASC",
    "added": "r.created_at DESC",
    "merchant": "r.merchant COLLATE NOCASE ASC",
}


def search(
    conn: Conn, f: Filters, text: str = "", limit: int = 50, offset: int = 0, sort: str | None = None,
) -> dict:
    cond, params = where(f)
    info: dict = {}
    if text.strip():
        scores, info = rank(conn, text)
        if not scores:
            return {"items": [], "total": 0, "summary": _empty_summary(), "search": info}
        marks = ",".join("?" * len(scores))
        rows = conn.execute(
            f"SELECT r.seq, r.id FROM receipts r WHERE r.seq IN ({marks}) AND {cond}", (*scores.keys(), *params)
        ).fetchall()
        ids_by_seq = {seq: rid for seq, rid in rows}
        if sort and sort in SORTS:
            order = conn.execute(
                f"SELECT r.seq FROM receipts r WHERE r.seq IN ({','.join('?' * len(ids_by_seq)) or 'NULL'}) "
                f"ORDER BY {SORTS[sort]}", tuple(ids_by_seq),
            ).fetchall()
            ordered = [r[0] for r in order]
        else:
            ordered = sorted(ids_by_seq, key=lambda s: scores[s], reverse=True)
        total = len(ordered)
        page = [ids_by_seq[s] for s in ordered[offset : offset + limit]]
        summ = _summary(conn, f"r.seq IN ({','.join('?' * len(ordered)) or 'NULL'})", ordered)
    else:
        order = SORTS.get(sort or "date", SORTS["date"])
        total = conn.execute(f"SELECT COUNT(*) FROM receipts r WHERE {cond}", params).fetchone()[0]
        page = [r[0] for r in conn.execute(
            f"SELECT r.id FROM receipts r WHERE {cond} ORDER BY {order} LIMIT ? OFFSET ?", (*params, limit, offset)
        )]
        summ = _summary(conn, cond, params)
    items = [records.summary(records.get(conn, rid)) for rid in page]
    return {"items": items, "total": total, "summary": summ, "search": info}


def all_ids(conn: Conn, f: Filters, text: str = "", sort: str | None = None) -> list[str]:
    """Every matching id, for exports."""
    out: list[str] = []
    offset = 0
    while True:
        page = search(conn, f, text, limit=500, offset=offset, sort=sort)
        out += [i["id"] for i in page["items"]]
        offset += 500
        if offset >= page["total"]:
            return out


def _empty_summary() -> dict:
    return {"count": 0, "total": 0.0, "tax": 0.0, "by_category": []}


def _summary(conn: sqlite3.Connection, cond: str, params) -> dict:
    row = conn.execute(
        f"SELECT COUNT(*), COALESCE(SUM(r.total), 0), COALESCE(SUM(r.tax), 0) FROM receipts r WHERE {cond}", params
    ).fetchone()
    cats = conn.execute(
        f"SELECT COALESCE(r.category, 'Uncategorized') AS name, COUNT(*) AS count, COALESCE(SUM(r.total), 0) AS total "
        f"FROM receipts r WHERE {cond} GROUP BY 1 ORDER BY total DESC",
        params,
    ).fetchall()
    return {
        "count": row[0],
        "total": round(row[1], 2),
        "tax": round(row[2], 2),
        "by_category": [dict(c) for c in cats],
    }
