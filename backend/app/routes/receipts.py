from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import images, nlquery, records, storage
from ..auth import User, current_user
from ..db import Conn, get_db
from ..search import Filters, search
from ..worker import worker

router = APIRouter(prefix="/api/receipts", tags=["receipts"])


def _not_found(exc: records.NotFound):
    return HTTPException(404, "No such receipt")


class FilterParams:
    """The list/search/export query string. `q` is plain English; explicit
    parameters win over what it says."""

    def __init__(
        self,
        q: str = "",
        date_from: str | None = None,
        date_to: str | None = None,
        min_total: float | None = None,
        max_total: float | None = None,
        merchant: str | None = None,
        category: str | None = None,
        tag: list[str] = Query(default=[]),
        payment_method: str | None = None,
        card_last4: str | None = None,
        status: str | None = None,
        created_by: str | None = None,
        reimbursed: bool | None = None,
        sort: str | None = None,
    ):
        self.q = q
        self.explicit = Filters(
            date_from=date_from, date_to=date_to, min_total=min_total, max_total=max_total, merchant=merchant,
            category=category, tags=list(tag), payment_method=payment_method, card_last4=card_last4,
            status=status, created_by=created_by, reimbursed=reimbursed,
        )
        self.sort = sort

    def resolve(self, conn: Conn, user: User) -> tuple[Filters, str, list[dict]]:
        f = self.explicit
        if not self.q.strip():
            return f, "", []
        parsed = nlquery.parse(
            self.q,
            today=date.today(),
            merchants=[r[0] for r in conn.execute("SELECT DISTINCT merchant FROM receipts WHERE merchant IS NOT NULL")],
            categories=[r[0] for r in conn.execute("SELECT name FROM categories")],
            tags=[r[0] for r in conn.execute("SELECT name FROM tags")],
            usernames=[r[0] for r in conn.execute("SELECT username FROM users")],
            current_user=user.username,
        )
        merged = Filters(
            date_from=f.date_from or parsed.date_from,
            date_to=f.date_to or parsed.date_to,
            min_total=f.min_total if f.min_total is not None else parsed.min_total,
            max_total=f.max_total if f.max_total is not None else parsed.max_total,
            merchant=f.merchant or parsed.merchant,
            category=f.category or parsed.category,
            tags=sorted(set(f.tags) | set(parsed.tags)),
            payment_method=f.payment_method or parsed.payment_method,
            card_last4=f.card_last4 or parsed.card_last4,
            status=f.status or parsed.status,
            created_by=f.created_by or parsed.created_by,
            reimbursed=f.reimbursed if f.reimbursed is not None else parsed.reimbursed,
        )
        return merged, parsed.text, [c.__dict__ for c in parsed.chips]


@router.get("")
def list_receipts(
    params: FilterParams = Depends(),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    conn: Conn = Depends(get_db),
):
    filters, text, chips = params.resolve(conn, user)
    result = search(conn, filters, text, limit=limit, offset=offset, sort=params.sort)
    result["query"] = {"chips": chips, "text": text, "filters": filters.__dict__}
    return result


@router.post("", status_code=202)
async def upload(
    files: list[UploadFile] = File(...),
    tags: list[str] = Form(default=[]),
    user: User = Depends(current_user),
    conn: Conn = Depends(get_db),
):
    created = []
    tags = [t for t in tags if t.strip()][:10]
    for upload in files:
        data = await upload.read(images.MAX_UPLOAD + 1)
        if len(data) > images.MAX_UPLOAD:
            raise HTTPException(413, f"{upload.filename} is over 25 MB")
        mime = images.sniff(data)
        if not mime:
            raise HTTPException(415, f"{upload.filename} isn't a JPEG, PNG, WebP or PDF")
        rid = records.create(conn, data, mime, upload.filename, user.username, tags)
        worker.ocr(rid)
        created.append({"id": rid, "status": "queued"})
    return {"receipts": created}


class Patch(BaseModel):
    merchant: str | None = Field(default=None, max_length=120)
    txn_date: str | None = None
    txn_time: str | None = None
    subtotal: float | None = None
    tax: float | None = None
    total: float | None = None
    payment_method: str | None = Field(default=None, max_length=40)
    card_last4: str | None = Field(default=None, max_length=4)
    category: str | None = Field(default=None, max_length=60)
    notes: str | None = Field(default=None, max_length=4000)
    tags: list[str] | None = None
    hsa: dict[str, Any] | None = None
    donation: dict[str, Any] | None = None
    warranty: dict[str, Any] | None = None
    line_items: list[dict[str, Any]] | None = None
    status: str | None = Field(default=None, pattern="^(review|confirmed)$")
    remember_category: bool = False


@router.get("/{receipt_id}")
def get_receipt(receipt_id: str, _: User = Depends(current_user), conn: Conn = Depends(get_db)):
    try:
        return records.get(conn, receipt_id)
    except records.NotFound as exc:
        raise _not_found(exc)


@router.patch("/{receipt_id}")
def patch_receipt(receipt_id: str, body: Patch, user: User = Depends(current_user), conn: Conn = Depends(get_db)):
    patch = body.model_dump(exclude_unset=True)
    remember = patch.pop("remember_category", False)
    try:
        rec = records.update(conn, receipt_id, patch, user.username, remember_category=remember)
    except records.NotFound as exc:
        raise _not_found(exc)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    worker.embed(receipt_id)
    return rec


@router.delete("/{receipt_id}")
def delete_receipt(receipt_id: str, _: User = Depends(current_user), conn: Conn = Depends(get_db)):
    try:
        records.delete(conn, receipt_id)
    except records.NotFound as exc:
        raise _not_found(exc)
    return {"ok": True}


@router.post("/{receipt_id}/reprocess", status_code=202)
def reprocess(receipt_id: str, _: User = Depends(current_user), conn: Conn = Depends(get_db)):
    try:
        rec = records.get(conn, receipt_id)
    except records.NotFound as exc:
        raise _not_found(exc)
    if rec["status"] != "confirmed":
        records.set_status(conn, receipt_id, "queued")
    worker.ocr(receipt_id, overwrite=rec["status"] != "confirmed")
    return {"id": receipt_id, "status": "queued"}


@router.get("/{receipt_id}/file")
def original_file(receipt_id: str, _: User = Depends(current_user), conn: Conn = Depends(get_db)):
    try:
        rec = records.get(conn, receipt_id)
    except records.NotFound as exc:
        raise _not_found(exc)
    path = storage.absolute(rec["file_path"])
    return FileResponse(path, media_type=rec["mime"], filename=path.name, content_disposition_type="inline",
                        headers={"Cache-Control": "private, max-age=300"})


@router.get("/{receipt_id}/preview")
def preview(receipt_id: str, w: int = 320, _: User = Depends(current_user), conn: Conn = Depends(get_db)):
    try:
        rec = records.get(conn, receipt_id)
    except records.NotFound as exc:
        raise _not_found(exc)
    path = images.preview(rec["file_path"], rec["mime"], w)
    # The name changes with the file, so the URL's ?v= can be cached hard.
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.post("/{receipt_id}/attachments")
async def add_attachment(
    receipt_id: str,
    file: UploadFile = File(...),
    label: str = Form(default=""),
    user: User = Depends(current_user),
    conn: Conn = Depends(get_db),
):
    data = await file.read(images.MAX_UPLOAD + 1)
    if len(data) > images.MAX_UPLOAD:
        raise HTTPException(413, "Over 25 MB")
    mime = images.sniff(data)
    if not mime:
        raise HTTPException(415, "Attach a JPEG, PNG, WebP or PDF")
    try:
        return records.add_attachment(conn, receipt_id, data, mime, file.filename, label[:60] or None, user.username)
    except records.NotFound as exc:
        raise _not_found(exc)


@router.get("/{receipt_id}/attachments/{attachment_id}")
def get_attachment(receipt_id: str, attachment_id: str, _: User = Depends(current_user), conn: Conn = Depends(get_db)):
    row = conn.execute(
        "SELECT file_path, mime FROM attachments WHERE id = ? AND receipt_id = ?", (attachment_id, receipt_id)
    ).fetchone()
    if not row:
        raise HTTPException(404, "No such attachment")
    path = storage.absolute(row["file_path"])
    return FileResponse(path, media_type=row["mime"], filename=path.name, content_disposition_type="inline")


@router.delete("/{receipt_id}/attachments/{attachment_id}")
def delete_attachment(receipt_id: str, attachment_id: str, _: User = Depends(current_user), conn: Conn = Depends(get_db)):
    try:
        return records.delete_attachment(conn, receipt_id, attachment_id)
    except records.NotFound:
        raise HTTPException(404, "No such attachment")
