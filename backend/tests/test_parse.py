from datetime import date
from pathlib import Path

import pytest

from app.parse import amounts_in, parse_date, parse_receipt, parse_time

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 28)


def parsed(name: str):
    return parse_receipt((FIXTURES / name).read_text(encoding="utf-8"), today=TODAY)


def test_walmart():
    p = parsed("walmart.txt")
    assert p.merchant == "Walmart"
    assert p.txn_date == "2026-03-14"
    assert p.txn_time == "14:32"
    assert (p.subtotal, p.tax, p.total) == (21.63, 1.07, 22.70)
    assert (p.payment_method, p.card_last4) == ("Visa", "4321")
    descriptions = [i.description for i in p.line_items]
    assert "BANANAS" in descriptions
    assert "MILK GAL 2%" in descriptions
    assert len(p.line_items) == 4


def test_starbucks_named_date_and_apple_pay():
    p = parsed("starbucks.txt")
    assert p.merchant == "STARBUCKS"
    assert p.txn_date == "2026-03-02"
    assert p.txn_time == "08:05"
    assert (p.subtotal, p.tax, p.total) == (9.40, 0.78, 10.18)
    assert p.payment_method == "Apple Pay"
    assert [i.amount for i in p.line_items] == [5.45, 3.95]


def test_home_depot_first_date_wins_over_return_policy():
    p = parsed("homedepot.txt")
    assert p.merchant == "THE HOME DEPOT"
    assert p.txn_date == "2026-01-09"
    assert p.txn_time == "18:12"
    assert (p.subtotal, p.tax, p.total) == (46.33, 3.82, 50.15)
    assert (p.payment_method, p.card_last4) == ("Mastercard", "1111")


def test_diner_grand_total_and_cash():
    p = parsed("diner.txt")
    assert p.merchant == "Joe's Diner"
    assert p.txn_date == "2025-10-05"
    assert p.txn_time == "19:41"
    assert (p.subtotal, p.tax, p.total) == (19.74, 1.78, 21.52)
    assert p.payment_method == "Cash"
    assert [i.description for i in p.line_items] == ["Cheeseburger", "Fries", "Iced Tea"]


def test_ocr_zero_for_o_and_iso_date():
    p = parsed("noisy.txt")
    assert p.merchant == "SHELL"
    assert p.txn_date == "2026-02-11"
    assert p.total == 34.68
    assert (p.payment_method, p.card_last4) == ("Debit", "9876")


def test_donation_letter_without_total_label():
    p = parsed("donation.txt")
    assert p.merchant == "Austin Pets Alive"
    assert p.txn_date == "2025-11-28"
    assert p.total == 300.00
    assert (p.payment_method, p.card_last4) == ("Credit", "5555")


def test_subtotal_plus_tax_fills_missing_total():
    p = parse_receipt("SHOP\nSUBTOTAL 10.00\nTAX 0.83\n", today=TODAY)
    assert p.total == 10.83


def test_tax_inferred_from_total_minus_subtotal():
    p = parse_receipt("SHOP\nSUBTOTAL 10.00\nTOTAL 10.83\n", today=TODAY)
    assert p.tax == 0.83


def test_label_and_amount_on_separate_lines():
    p = parse_receipt("SHOP\nTOTAL\n$ 42.10\n", today=TODAY)
    assert p.total == 42.10


def test_multiple_tax_lines_add_up():
    p = parse_receipt("SHOP\nSUBTOTAL 100.00\nSTATE TAX 6.25\nCITY TAX 2.00\nTOTAL 108.25\n", today=TODAY)
    assert p.tax == 8.25


@pytest.mark.parametrize(
    "text,expected",
    [
        ("03/04/2026", "2026-03-04"),
        ("3-4-26", "2026-03-04"),
        ("25/12/2025", "2025-12-25"),  # day first when the first number can't be a month
        ("Sept 9, 2025", "2025-09-09"),
        ("9 Sep 2025", "2025-09-09"),
        ("2026.01.31", "2026-01-31"),
        ("12/31/2030", None),  # too far in the future
        ("13/13/2025", None),
    ],
)
def test_parse_date(text, expected):
    assert parse_date(text, "MDY", TODAY) == expected


def test_parse_date_dmy_locale():
    assert parse_date("03/04/2026", "DMY", TODAY) == "2026-04-03"


@pytest.mark.parametrize(
    "text,expected",
    [("12:05 AM", "00:05"), ("12:30 PM", "12:30"), ("7:41 pm", "19:41"), ("23:59", "23:59"), ("99:99", None)],
)
def test_parse_time(text, expected):
    assert parse_time(text) == expected


def test_amounts_ignore_rates_and_long_numbers():
    assert amounts_in("TAX 1 8.250 % 1.07") == [1.07]
    assert amounts_in("GALLONS 10.512 @ 3.299") == []
    assert amounts_in("TOTAL 1,234.56") == [1234.56]
    assert amounts_in("OCR comma 12,34") == [12.34]
    assert amounts_in("REFUND -3.00") == [-3.0]


def test_ocr_letter_digit_swaps_in_amounts():
    p = parse_receipt("CVS pharmacy\nSUBTOTAL 25.00\nTAX @.00\nTOTAL 25.O0\nDEBLT CARD\n", today=TODAY)
    assert (p.subtotal, p.tax, p.total) == (25.0, 0.0, 25.0)
    assert p.payment_method == "Debit"
    # Words stay words.
    assert amounts_in("SOLD IS.OK") == []


@pytest.mark.parametrize(
    "text,expected",
    [
        ("11-Oct-2026 7:43:05P", "2026-10-11"),
        ("11-0ct-2026 7:43:05P", "2026-10-11"),  # OCR's zero for O
        ("10182026 18:55:18", "2026-10-18"),  # slashes too faint to scan
        ("REF 10182026", None),  # eight digits alone could be anything
    ],
)
def test_more_date_shapes(text, expected):
    assert parse_date(text, "MDY", TODAY) == expected


def test_single_letter_pm():
    assert parse_time("11-Oct-2026 7:43:05P") == "19:43"


def test_lines_from_tilted_boxes():
    from app.ocr import lines_from_boxes

    def box(x, y, w, h, slope):
        # A text box on a page tilted by `slope` (dy per dx).
        return [[x, y], [x + w, y + w * slope], [x + w, y + h + w * slope], [x, y + h]]

    slope = 0.06  # about 3.4 degrees, a hand-held photo
    boxes = [
        box(100, 100, 300, 40, slope),             # a big logo line
        box(100, 160, 160, 20, slope),             # address under it
        box(100, 300, 120, 20, slope),             # TOTAL ...
        box(600, 300 + 500 * slope, 80, 20, slope),  # ... and its amount, far right, lower on the tilt
    ]
    text = lines_from_boxes(boxes, ["CVS pharmacy", "110 WEST MAIN ST", "TOTAL", "17.49"])
    assert text.splitlines() == ["CVS pharmacy", "110 WEST MAIN ST", "TOTAL 17.49"]
