"""Dashboard, reports and exports."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response, StreamingResponse

from .. import records, storage
from ..auth import User, current_user
from ..db import Conn, get_db
from ..search import all_ids
from ..worker import worker
from .receipts import FilterParams

router = APIRouter(prefix="/api", tags=["reports"])


def _year_bounds(year: int | None) -> tuple[str, str]:
    year = year or date.today().year
    return f"{year}-01-01", f"{year}-12-31"


def _sum(conn: Conn, where: str, params: tuple) -> dict:
    row = conn.execute(
        f"SELECT COUNT(*), COALESCE(ROUND(SUM(total), 2), 0), COALESCE(ROUND(SUM(tax), 2), 0) FROM receipts WHERE {where}",
        params,
    ).fetchone()
    return {"count": row[0], "total": row[1], "tax": row[2]}


@router.get("/dashboard")
def dashboard(user: User = Depends(current_user), conn: Conn = Depends(get_db)):
    today = date.today()
    year_start = today.replace(month=1, day=1).isoformat()
    soon = (today + timedelta(days=60)).isoformat()
    recent = [r[0] for r in conn.execute("SELECT id FROM receipts ORDER BY created_at DESC LIMIT 5")]
    hsa = conn.execute(
        "SELECT COUNT(*), COALESCE(ROUND(SUM(COALESCE(h.eligible_amount, r.total)), 2), 0) FROM receipts r "
        "JOIN receipt_tags t ON t.receipt_id = r.id JOIN tags g ON g.name = t.tag AND g.kind = 'hsa' "
        "LEFT JOIN hsa h ON h.receipt_id = r.id WHERE COALESCE(h.reimbursed, 0) = 0"
    ).fetchone()
    warranties = conn.execute(
        "SELECT r.id, r.merchant, w.product, w.expires_on FROM warranty w JOIN receipts r ON r.id = w.receipt_id "
        "WHERE w.expires_on BETWEEN ? AND ? ORDER BY w.expires_on",
        (today.isoformat(), soon),
    ).fetchall()
    # This year's receipts carrying a tag of each kind (HSA, donation, warranty).
    by_kind = {
        kind: {"count": count, "total": total}
        for kind, count, total in conn.execute(
            "SELECT g.kind, COUNT(DISTINCT r.id), COALESCE(ROUND(SUM(r.total), 2), 0) FROM receipts r "
            "JOIN receipt_tags t ON t.receipt_id = r.id JOIN tags g ON g.name = t.tag "
            "WHERE r.txn_date >= ? AND g.kind != 'plain' GROUP BY g.kind",
            (year_start,),
        )
    }
    return {
        "year": today.year,
        "this_year": _sum(conn, "txn_date >= ?", (year_start,)) | {"by_kind": by_kind},
        "review_count": conn.execute("SELECT COUNT(*) FROM receipts WHERE status IN ('review', 'failed')").fetchone()[0],
        "processing_count": conn.execute(
            "SELECT COUNT(*) FROM receipts WHERE status IN ('queued', 'processing')").fetchone()[0],
        "hsa_unreimbursed": {"count": hsa[0], "total": hsa[1]},
        "warranties_expiring": [dict(w) for w in warranties],
        "recent": [records.summary(records.get(conn, rid)) for rid in recent],
    }


@router.get("/reports/overview")
def overview(year: int | None = None, _: User = Depends(current_user), conn: Conn = Depends(get_db)):
    start, end = _year_bounds(year)
    params = (start, end)
    base = "txn_date BETWEEN ? AND ?"
    by_month = conn.execute(
        f"SELECT substr(txn_date, 1, 7) AS month, COUNT(*) AS count, ROUND(SUM(total), 2) AS total, "
        f"ROUND(SUM(tax), 2) AS tax FROM receipts WHERE {base} GROUP BY 1 ORDER BY 1",
        params,
    ).fetchall()
    by_category = conn.execute(
        f"SELECT COALESCE(category, 'Uncategorized') AS name, COUNT(*) AS count, ROUND(SUM(total), 2) AS total "
        f"FROM receipts WHERE {base} GROUP BY 1 ORDER BY total DESC",
        params,
    ).fetchall()
    by_merchant = conn.execute(
        f"SELECT merchant AS name, COUNT(*) AS count, ROUND(SUM(total), 2) AS total FROM receipts "
        f"WHERE {base} AND merchant IS NOT NULL GROUP BY 1 ORDER BY total DESC LIMIT 15",
        params,
    ).fetchall()
    years = [r[0] for r in conn.execute(
        "SELECT DISTINCT substr(txn_date, 1, 4) FROM receipts WHERE txn_date IS NOT NULL ORDER BY 1 DESC")]
    return {
        "year": int(start[:4]),
        "years": years,
        "totals": _sum(conn, base, params),
        "by_month": [dict(r) for r in by_month],
        "by_category": [dict(r) for r in by_category],
        "by_merchant": [dict(r) for r in by_merchant],
    }


@router.get("/reports/hsa")
def hsa_report(year: int | None = None, _: User = Depends(current_user), conn: Conn = Depends(get_db)):
    where = "g.kind = 'hsa'"
    params: tuple = ()
    if year:
        where += " AND r.txn_date BETWEEN ? AND ?"
        params = _year_bounds(year)
    rows = conn.execute(
        "SELECT r.id, r.txn_date, r.merchant, r.total, h.patient, h.provider, h.eligible_amount, "
        "COALESCE(h.reimbursed, 0) AS reimbursed, h.reimbursed_date, h.claim_ref FROM receipts r "
        "JOIN receipt_tags t ON t.receipt_id = r.id JOIN tags g ON g.name = t.tag "
        f"LEFT JOIN hsa h ON h.receipt_id = r.id WHERE {where} ORDER BY r.txn_date DESC",
        params,
    ).fetchall()
    items = [dict(r) | {"reimbursed": bool(r["reimbursed"]), "amount": r["eligible_amount"] if r["eligible_amount"] is not None else r["total"]} for r in rows]
    by_patient: dict[str, dict] = {}
    for it in items:
        p = by_patient.setdefault(it["patient"] or "Unassigned", {"name": it["patient"] or "Unassigned", "total": 0.0, "unreimbursed": 0.0})
        p["total"] = round(p["total"] + (it["amount"] or 0), 2)
        if not it["reimbursed"]:
            p["unreimbursed"] = round(p["unreimbursed"] + (it["amount"] or 0), 2)
    return {
        "items": items,
        "total": round(sum(i["amount"] or 0 for i in items), 2),
        "unreimbursed": round(sum(i["amount"] or 0 for i in items if not i["reimbursed"]), 2),
        "by_patient": list(by_patient.values()),
    }


@router.get("/reports/donations")
def donations_report(year: int | None = None, _: User = Depends(current_user), conn: Conn = Depends(get_db)):
    start, end = _year_bounds(year)
    ids = [r[0] for r in conn.execute(
        "SELECT r.id FROM receipts r JOIN receipt_tags t ON t.receipt_id = r.id JOIN tags g ON g.name = t.tag "
        "WHERE g.kind = 'donation' AND r.txn_date BETWEEN ? AND ? ORDER BY r.txn_date",
        (start, end),
    )]
    items, by_org = [], {}
    for rid in ids:
        rec = records.get(conn, rid)
        d = rec.get("donation") or {}
        amount = d.get("deductible_amount") if d.get("deductible_amount") is not None else rec.get("total")
        org = d.get("organization") or rec.get("merchant") or "Unknown"
        items.append({
            "id": rid, "txn_date": rec["txn_date"], "organization": org, "ein": d.get("ein"),
            "donation_type": d.get("donation_type") or "cash", "amount": amount,
            "items_description": d.get("items_description"), "needs_acknowledgment": rec["needs_acknowledgment"],
        })
        o = by_org.setdefault(org, {"name": org, "ein": d.get("ein"), "count": 0, "total": 0.0})
        o["count"] += 1
        o["total"] = round(o["total"] + (amount or 0), 2)
    return {
        "year": int(start[:4]),
        "items": items,
        "by_organization": sorted(by_org.values(), key=lambda o: -o["total"]),
        "cash_total": round(sum(i["amount"] or 0 for i in items if i["donation_type"] == "cash"), 2),
        "noncash_total": round(sum(i["amount"] or 0 for i in items if i["donation_type"] == "noncash"), 2),
        "needs_acknowledgment": [i for i in items if i["needs_acknowledgment"]],
    }


@router.get("/reports/warranties")
def warranties_report(_: User = Depends(current_user), conn: Conn = Depends(get_db)):
    rows = conn.execute(
        "SELECT r.id, r.merchant, r.txn_date, r.total, w.product, w.serial, w.expires_on FROM warranty w "
        "JOIN receipts r ON r.id = w.receipt_id ORDER BY w.expires_on IS NULL, w.expires_on"
    ).fetchall()
    today = date.today().isoformat()
    items = [dict(r) | {"expired": bool(r["expires_on"] and r["expires_on"] < today)} for r in rows]
    return {"items": items}


# --- exports -------------------------------------------------------------------

CSV_COLUMNS = [
    "id", "status", "txn_date", "txn_time", "merchant", "category", "tags", "subtotal", "tax", "total",
    "payment_method", "card_last4", "notes", "hsa_patient", "hsa_provider", "hsa_eligible_amount", "hsa_reimbursed",
    "hsa_reimbursed_date", "donation_organization", "donation_ein", "donation_type", "donation_deductible_amount",
    "donation_acknowledgment", "warranty_product", "warranty_serial", "warranty_expires_on", "file", "created_by",
]


def _csv_row(rec: dict) -> dict:
    row = {k: rec.get(k) for k in CSV_COLUMNS if k in rec}
    row["tags"] = "; ".join(rec.get("tags", []))
    row["file"] = rec["file_path"]
    for kind in ("hsa", "donation", "warranty"):
        for k, v in (rec.get(kind) or {}).items():
            col = f"{kind}_{k}" if not k.startswith(kind) else k
            if col in CSV_COLUMNS:
                row[col] = v
    return row


def _csv_bytes(recs: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for rec in recs:
        writer.writerow(_csv_row(rec))
    # Excel opens UTF-8 CSVs correctly only with the BOM.
    return ("﻿" + buf.getvalue()).encode("utf-8")


def _export_records(params: FilterParams, user: User, conn: Conn) -> list[dict]:
    filters, text, _ = params.resolve(conn, user)
    return [records.get(conn, rid) for rid in all_ids(conn, filters, text, sort=params.sort or "date_asc")]


def _stamp() -> str:
    return date.today().isoformat()


@router.get("/export.csv")
def export_csv(params: FilterParams = Depends(), user: User = Depends(current_user), conn: Conn = Depends(get_db)):
    data = _csv_bytes(_export_records(params, user, conn))
    return Response(data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="receipts-{_stamp()}.csv"'})


@router.get("/export.json")
def export_json(params: FilterParams = Depends(), user: User = Depends(current_user), conn: Conn = Depends(get_db)):
    recs = [records.to_sidecar(r) | {"path": r["file_path"]} for r in _export_records(params, user, conn)]
    totals = {"count": len(recs), "total": round(sum(r.get("total") or 0 for r in recs), 2),
              "tax": round(sum(r.get("tax") or 0 for r in recs), 2)}
    body = json.dumps({"exported_at": records.now(), "summary": totals, "receipts": recs}, indent=2, default=str)
    return Response(body, media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="receipts-{_stamp()}.json"'})


@router.get("/export.zip")
def export_zip(
    params: FilterParams = Depends(),
    name: str = Query("receipts", max_length=60),
    user: User = Depends(current_user),
    conn: Conn = Depends(get_db),
):
    """A package for the accountant or the HSA claim: the CSV plus every
    original image, PDF and attachment, laid out as on disk."""
    recs = _export_records(params, user, conn)
    safe = storage.slug(name, fallback="receipts")

    def stream():
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{safe}/{safe}.csv", _csv_bytes(recs))
            for rec in recs:
                paths = [rec["file_path"]] + [a["file_path"] for a in rec["attachments"]]
                for rel in paths:
                    src = storage.absolute(rel)
                    if src.exists():
                        zf.write(src, f"{safe}/files/{rel}", compress_type=zipfile.ZIP_STORED)
        buf.seek(0)
        yield from iter(lambda: buf.read(1 << 16), b"")

    return StreamingResponse(stream(), media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{safe}-{_stamp()}.zip"'})


@router.get("/status")
def status(_: User = Depends(current_user)):
    return {"queue": worker.pending(), "current": worker.current}
