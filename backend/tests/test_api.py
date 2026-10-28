import csv
import dataclasses
import io
import json
import zipfile
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app import config
from app.worker import worker

from .conftest import TESSERACT

H = {"X-Requested-With": "fetch"}
TODAY = date.today()
RECEIPT_DATE = date(TODAY.year, 1, 15) if TODAY.month > 1 else date(TODAY.year - 1, 12, 15)


def receipt_png(lines: list[str]) -> bytes:
    """A clean, receipt-shaped image Tesseract can read."""
    try:
        font = ImageFont.truetype("DejaVuSansMono.ttf", 34)
    except OSError:
        try:
            font = ImageFont.truetype("consola.ttf", 34)
        except OSError:
            font = ImageFont.load_default(size=34)
    img = Image.new("L", (900, 80 + 52 * len(lines)), 255)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((50, 40 + 52 * i), line, fill=0, font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


WALMART = [
    "WALMART",
    "1234 N LAMAR BLVD",
    "AUSTIN TX 78756",
    "BANANAS              1.24",
    "MILK GALLON          3.48",
    "PAPER TOWELS        12.97",
    "SUBTOTAL            17.69",
    "TAX                  1.46",
    "TOTAL               19.15",
    "VISA TEND           19.15",
    f"{RECEIPT_DATE:%m/%d/%y} 14:32",
]


@pytest.fixture
def client(settings):
    from app.main import app

    with TestClient(app) as c:
        yield c
    worker.drain()


def signed_in(client: TestClient) -> TestClient:
    r = client.post("/api/auth/setup", json={"username": "alex", "display_name": "Alex", "password": "correct horse"}, headers=H)
    assert r.status_code == 200, r.text
    return client


def upload(client, data: bytes, name="r.png") -> str:
    r = client.post("/api/receipts", files=[("files", (name, data, "image/png"))], headers=H)
    assert r.status_code == 202, r.text
    return r.json()["receipts"][0]["id"]


def test_setup_login_and_guards(client):
    state = client.get("/api/auth/state").json()
    assert (state["needs_setup"], state["user"]) == (True, None)
    assert state["server"]["currency"] == "USD"
    assert client.get("/api/receipts").status_code == 401
    signed_in(client)
    assert client.get("/api/auth/state").json()["user"]["role"] == "admin"
    # A second setup is refused.
    assert client.post("/api/auth/setup", json={"username": "x1", "password": "12345678"}, headers=H).status_code == 409
    # Writes without the header are refused (CSRF).
    assert client.post("/api/auth/logout").status_code == 403
    client.post("/api/auth/logout", headers=H)
    assert client.get("/api/receipts").status_code == 401
    assert client.post("/api/auth/login", json={"username": "alex", "password": "nope"}, headers=H).status_code == 401
    assert client.post("/api/auth/login", json={"username": "ALEX", "password": "correct horse"}, headers=H).status_code == 200
    # Members can be added by the admin and can't add users themselves.
    r = client.post("/api/users", json={"username": "sam", "password": "password1", "role": "member"}, headers=H)
    assert r.status_code == 200
    client.post("/api/auth/logout", headers=H)
    client.post("/api/auth/login", json={"username": "sam", "password": "password1"}, headers=H)
    assert client.post("/api/users", json={"username": "eve", "password": "password1"}, headers=H).status_code == 403


def test_rejects_non_images(client):
    signed_in(client)
    r = client.post("/api/receipts", files=[("files", ("x.txt", b"hello", "image/png"))], headers=H)
    assert r.status_code == 415


@pytest.mark.skipif(not TESSERACT, reason="tesseract not installed")
def test_scan_files_itself_with_tags_from_upload(client):
    signed_in(client)
    r = client.post("/api/receipts", files=[("files", ("r.png", receipt_png(WALMART), "image/png"))],
                    data={"tags": ["HSA"]}, headers=H)
    rid = r.json()["receipts"][0]["id"]
    worker.drain()
    rec = client.get(f"/api/receipts/{rid}").json()
    assert rec["status"] == "confirmed", rec.get("error")
    assert rec["tags"] == ["HSA"]
    assert rec["file_path"].startswith(f"{RECEIPT_DATE:%Y}/{RECEIPT_DATE:%m}/Groceries/")


def test_scan_review_confirm_file_away(client, monkeypatch):
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, auto_file=False))
    signed_in(client)
    rid = upload(client, receipt_png(WALMART))
    worker.drain()
    rec = client.get(f"/api/receipts/{rid}").json()
    assert rec["status"] == "review", rec.get("error")
    assert rec["merchant"] == "Walmart"
    assert rec["total"] == 19.15
    assert rec["tax"] == 1.46
    assert rec["txn_date"] == RECEIPT_DATE.isoformat()
    assert rec["payment_method"] == "Visa"
    assert rec["category"] == "Groceries"
    assert rec["file_path"].startswith("_inbox/")

    r = client.patch(f"/api/receipts/{rid}", json={"status": "confirmed", "notes": "weekly shop"}, headers=H)
    rec = r.json()
    expected_dir = f"{RECEIPT_DATE:%Y}/{RECEIPT_DATE:%m}/Groceries/"
    assert rec["file_path"] == f"{expected_dir}{RECEIPT_DATE.isoformat()}_Walmart_19.15_{rid}.png"
    root = config.settings.receipts_dir
    sidecar = json.loads((root / rec["sidecar_path"]).read_text())
    assert sidecar["notes"] == "weekly shop"
    assert sidecar["ocr"]["parsed"]["total"] == 19.15
    assert "WALMART" in sidecar["ocr"]["text"]
    assert sidecar["history"][-1]["by"] == "alex"
    assert not (root / "_inbox" / f"{rid}.png").exists()

    # Changing the category moves the files.
    rec = client.patch(f"/api/receipts/{rid}", json={"category": "Shopping"}, headers=H).json()
    assert "/Shopping/" in rec["file_path"]
    assert (root / rec["file_path"]).exists()
    assert not (root / expected_dir).exists()  # the emptied folder is gone

    # Search by plain English, by typo and by merchant.
    found = client.get("/api/receipts", params={"q": "walmart over $10"}).json()
    assert [i["id"] for i in found["items"]] == [rid]
    assert {c["key"] for c in found["query"]["chips"]} == {"min_total", "merchant"}
    assert client.get("/api/receipts", params={"q": "bananna"}).json()["total"] == 1
    assert client.get("/api/receipts", params={"q": "walmart under $5"}).json()["total"] == 0

    # Lose the database: it rebuilds from the folder.
    from app import records
    from app.db import session

    with session() as conn:
        assert records.reindex_all(conn) == 1
    rec2 = client.get(f"/api/receipts/{rid}").json()
    assert rec2["category"] == "Shopping"
    assert rec2["notes"] == "weekly shop"

    # Delete: to the trash, not gone.
    assert client.delete(f"/api/receipts/{rid}", headers=H).status_code == 200
    assert client.get(f"/api/receipts/{rid}").status_code == 404
    assert list((root / "_trash").rglob("*.png"))


def no_ocr(monkeypatch):
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, ocr_enabled=False))


def _manual_receipt(client, **fields) -> str:
    """An upload with OCR off, filled in by hand."""
    rid = upload(client, receipt_png(["X"]))
    worker.drain()
    r = client.patch(f"/api/receipts/{rid}", json=fields, headers=H)
    assert r.status_code == 200, r.text
    return rid


def test_hsa_donation_and_reports(client, monkeypatch):
    no_ocr(monkeypatch)
    signed_in(client)
    y = TODAY.year
    hsa_id = _manual_receipt(
        client, merchant="CVS", txn_date=f"{y}-02-03", total=45.20, category="Medical", status="confirmed",
        tags=["HSA"], hsa={"patient": "Alex", "provider": "CVS Pharmacy", "reimbursed": False},
    )
    gift_id = _manual_receipt(
        client, merchant="Austin Pets Alive", txn_date=f"{y}-03-01", total=300, category="Donations",
        status="confirmed", tags=["Donation"], donation={"organization": "Austin Pets Alive", "donation_type": "cash"},
    )
    _manual_receipt(client, merchant="Costco", txn_date=f"{y}-03-02", total=120.5, category="Groceries", status="confirmed")

    rec = client.get(f"/api/receipts/{gift_id}").json()
    assert rec["needs_acknowledgment"] is True
    assert rec["kinds"] == ["donation"]

    dash = client.get("/api/dashboard").json()
    assert dash["hsa_unreimbursed"] == {"count": 1, "total": 45.2}

    found = client.get("/api/receipts", params={"q": "unreimbursed hsa"}).json()
    assert [i["id"] for i in found["items"]] == [hsa_id]

    client.patch(f"/api/receipts/{hsa_id}", json={"hsa": {"reimbursed": True, "reimbursed_date": f"{y}-04-01"}}, headers=H)
    assert client.get("/api/dashboard").json()["hsa_unreimbursed"]["count"] == 0
    hsa = client.get("/api/reports/hsa").json()
    assert hsa["items"][0]["reimbursed"] is True
    assert hsa["items"][0]["patient"] == "Alex"  # kept from the first edit

    don = client.get("/api/reports/donations", params={"year": y}).json()
    assert don["cash_total"] == 300
    assert len(don["needs_acknowledgment"]) == 1
    # Attaching the charity's letter clears the flag.
    client.post(f"/api/receipts/{gift_id}/attachments", files={"file": ("ack.png", receipt_png(["THANK YOU"]), "image/png")},
                data={"label": "Acknowledgment letter"}, headers=H)
    assert client.get(f"/api/receipts/{gift_id}").json()["needs_acknowledgment"] is False

    overview = client.get("/api/reports/overview", params={"year": y}).json()
    assert overview["totals"]["count"] == 3
    assert overview["by_category"][0]["name"] == "Donations"

    # Exports follow the same filters as the list.
    r = client.get("/api/export.csv", params={"tag": "Donation"})
    rows = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert [row["merchant"] for row in rows] == ["Austin Pets Alive"]
    assert rows[0]["donation_type"] == "cash"
    r = client.get("/api/export.zip", params={"q": f"donations {y}", "name": f"Donations {y}"})
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert f"Donations-{y}/Donations-{y}.csv" in names
    assert sum("/files/" in n for n in names) == 2  # the receipt and its letter


def test_remember_category_creates_a_rule(client, monkeypatch):
    no_ocr(monkeypatch)
    signed_in(client)
    _manual_receipt(client, merchant="Bob's Bait", category="Entertainment", remember_category=True)
    r = client.post("/api/rules/test", json={"merchant": "Bob's Bait"}, headers=H).json()
    assert r["category"] == "Entertainment"


def test_spa_fallback(client, settings):
    static = settings.static_dir
    static.mkdir(parents=True)
    (static / "index.html").write_text("<html>app</html>")
    assert client.get("/review").text == "<html>app</html>"
    assert client.get("/api/nope").status_code == 404
