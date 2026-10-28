from datetime import date

import pytest

from app.nlquery import parse

TODAY = date(2026, 10, 28)  # a Wednesday
MERCHANTS = ["Costco", "Starbucks", "The Home Depot", "Whole Foods", "Walmart"]
CATEGORIES = ["Groceries", "Dining", "Utilities", "Hardware", "Transport", "Medical", "Shopping", "Donations", "Other"]
TAGS = ["HSA", "Donation", "Warranty", "Business"]


def q(text, **kw):
    return parse(text, TODAY, MERCHANTS, CATEGORIES, TAGS, ["alex", "sam"], current_user="alex", **kw)


def test_merchant_amount_and_relative_month():
    r = q("costco over $50 last month")
    assert r.merchant == "Costco"
    assert r.min_total == 50
    assert (r.date_from, r.date_to) == ("2026-09-01", "2026-09-30")
    assert r.text == ""
    assert [c.key for c in r.chips] == ["min_total", "date", "merchant"]


def test_category_in_named_month_picks_most_recent_past():
    r = q("dining in march")
    assert r.category == "Dining"
    assert (r.date_from, r.date_to) == ("2026-03-01", "2026-03-31")
    r = q("groceries december")
    assert r.category == "Groceries"
    assert (r.date_from, r.date_to) == ("2025-12-01", "2025-12-31")


def test_month_with_year_and_may_as_a_verb():
    assert q("march 2025").date_from == "2025-03-01"
    r = q("may 2025")
    assert (r.date_from, r.date_to) == ("2025-05-01", "2025-05-31")
    assert q("in may").date_from == "2026-05-01"
    assert q("receipts i may need").date_from is None


def test_typo_merchant():
    r = q("starbcks this year")
    assert r.merchant == "Starbucks"
    assert (r.date_from, r.date_to) == ("2026-01-01", "2026-10-28")


def test_partial_merchant_name():
    assert q("home depot").merchant == "The Home Depot"
    assert q("food").merchant is None  # too short a part of "Whole Foods"


def test_amount_range_and_max():
    r = q("between 20 and 50")
    assert (r.min_total, r.max_total) == (20, 50)
    assert q("under $15").max_total == 15
    assert q("less than 100").max_total == 100
    r = q("$12.34")
    assert (r.min_total, r.max_total) == (12.34, 12.34)


def test_date_range_and_since():
    r = q("between jan 5 and feb 10")
    assert (r.date_from, r.date_to) == ("2026-01-05", "2026-02-10")
    assert (r.min_total, r.max_total) == (None, None)
    r = q("since 9/1")
    assert (r.date_from, r.date_to) == ("2026-09-01", None)
    r = q("before 2026-01-01")
    assert (r.date_from, r.date_to) == (None, "2025-12-31")


def test_quarter_year_and_relative_weeks():
    assert (q("q1").date_from, q("q1").date_to) == ("2026-01-01", "2026-03-31")
    assert q("q4 2025").date_from == "2025-10-01"
    assert (q("2025").date_from, q("2025").date_to) == ("2025-01-01", "2025-12-31")
    assert (q("last week").date_from, q("last week").date_to) == ("2026-10-19", "2026-10-25")
    assert q("past 30 days").date_from == "2026-09-28"
    assert q("yesterday").date_from == "2026-10-27"


def test_payment_and_card():
    r = q("visa card 4321")
    assert (r.payment_method, r.card_last4) == ("Visa", "4321")
    assert q("paid with apple pay").payment_method == "Apple Pay"


def test_hsa_and_donations():
    r = q("unreimbursed hsa")
    assert r.reimbursed is False
    assert r.tags == ["HSA"]
    r = q("donations 2025")
    assert r.tags == ["Donation"]
    assert r.date_from == "2025-01-01"
    assert r.category is None


def test_people_and_status():
    assert q("mine").created_by == "alex"
    assert q("sam's dining").created_by == "sam"
    assert q("needs review").status == "review"


def test_leftover_text_for_semantic_search():
    r = q("coffee last month")
    assert r.text == "coffee"
    assert r.merchant is None
    r = q("show me pet stuff")
    assert r.text == "pet"
