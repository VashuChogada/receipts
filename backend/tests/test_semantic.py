"""Meaning-based search with the real model. Needs it in backend/.models
(downloaded on the first run, ~67 MB); skipped when that isn't possible."""

import dataclasses
from pathlib import Path

import pytest

from app import config, records
from app.db import session
from app.embed import embedder
from app.search import Filters, search
from app.worker import run_embed

MODELS = Path(__file__).resolve().parent.parent / ".models"

DOCS = {
    "Starbucks": ("Dining", ["Grande Latte", "Butter Croissant"]),
    "Chewy": ("Shopping", ["Purina Pro Plan dog food 30lb", "Cat litter"]),
    "The Home Depot": ("Hardware", ["2X4X8 STUD", "WOOD SCREWS 1LB"]),
    "Walmart": ("Groceries", ["BANANAS", "MILK GALLON"]),
    "CVS": ("Medical", ["AMOXICILLIN 500MG RX"]),
    "Shell": ("Transport", ["FUEL SALE REGULAR"]),
}


@pytest.fixture
def semantic(monkeypatch, db):
    if not db.vec_enabled:
        pytest.skip("sqlite-vec unavailable")
    monkeypatch.setattr(config, "settings", dataclasses.replace(
        config.settings, semantic_search=True, model_cache=MODELS))
    embedder._failed = False
    try:
        if embedder.query("warm up") is None:
            pytest.skip("embedding model unavailable")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"embedding model unavailable: {exc}")
    yield
    embedder.unload()


def test_meaning_finds_the_right_receipt(semantic, db):
    ids = {}
    for merchant, (category, items) in DOCS.items():
        rid = records.create(db, b"\xff\xd8\xff fake", "image/jpeg", "x.jpg", "alex")
        records.update(db, rid, {"merchant": merchant, "category": category, "total": 10,
                                 "line_items": [{"description": d, "amount": 1} for d in items]}, "alex")
        run_embed(rid)
        ids[merchant] = rid
    with session() as conn:
        for query, expected in [("coffee", "Starbucks"), ("pet supplies", "Chewy"), ("lumber", "The Home Depot"),
                                ("medicine", "CVS"), ("gasoline", "Shell"), ("milk", "Walmart")]:
            result = search(conn, Filters(), query)
            assert result["search"]["meaning_ran"]
            assert result["items"], query
            assert result["items"][0]["id"] == ids[expected], (query, [i["merchant"] for i in result["items"]])
            # Nothing unrelated tags along.
            assert len(result["items"]) <= 2, (query, [i["merchant"] for i in result["items"]])
