import pytest

from app import merchants


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("WAL-MART SUPERCENTER #1234", "Walmart"),
        ("Walmart", "Walmart"),
        ("C0STCO WHOLESALE #0045", "Costco"),
        ("THE HOME DEPOT 6524", "The Home Depot"),
        ("STARBUCKS Store #12345", "Starbucks"),
        ("Joe's Diner", "Joe's Diner"),
        ("JOE'S DINER", "Joe's Diner"),
        ("ACME WIDGETS INC.", "Acme Widgets"),
        ("SHELL", "Shell"),
        ("", None),
        ("###", None),
    ],
)
def test_normalize(raw, expected):
    assert merchants.normalize(raw) == expected


def test_fix_ocr_letters_only_inside_words():
    assert merchants.clean("C0STCO") == "COSTCO"
    assert merchants.clean("ROUTE 66 DINER") == "ROUTE 66 DINER"


def test_fuzzy_find_tolerates_typos():
    known = ["Starbucks", "Walmart", "Whole Foods", "The Home Depot"]
    assert merchants.fuzzy_find("starbcks", known)[0][0] == "Starbucks"
    assert merchants.fuzzy_find("home depo", known)[0][0] == "The Home Depot"
    assert merchants.fuzzy_find("zz", known) == []


def test_resolve_uses_alias_then_fuzzy(db):
    merchants.learn(db, "SPROUTS FARMERS MKT #12", "Sprouts")
    assert merchants.resolve(db, "SPROUTS FARMERS MKT #12") == "Sprouts"
    db.execute(
        "INSERT INTO receipts (id, status, merchant, file_path, sidecar_path, mime, created_at, updated_at) "
        "VALUES ('r1', 'confirmed', 'Luby''s Cafeteria', 'x', 'x', 'image/jpeg', 'now', 'now')"
    )
    assert merchants.resolve(db, "LUBYS CAFETERIA") == "Luby's Cafeteria"
