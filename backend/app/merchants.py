"""Merchant names: from what OCR read to the name the household knows.

`WAL-MART SUPERCENTER #1234` and `WALMART` are one merchant, `Walmart`. The
alias table learns from every confirmation, so the second receipt from a
place gets the name the user typed for the first.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone

from rapidfuzz import fuzz, process

# Well-known chains, so the first receipt already gets a clean name.
KNOWN = {
    "walmart": "Walmart", "walmartsupercenter": "Walmart", "walmartneighborhoodmarket": "Walmart",
    "costco": "Costco", "costcowholesale": "Costco", "target": "Target", "superTarget".lower(): "Target",
    "kroger": "Kroger", "heb": "H-E-B", "wholefoods": "Whole Foods", "wholefoodsmarket": "Whole Foods",
    "traderjoes": "Trader Joe's", "aldi": "Aldi", "publix": "Publix", "safeway": "Safeway",
    "sprouts": "Sprouts", "sproutsfarmersmarket": "Sprouts", "wegmans": "Wegmans", "meijer": "Meijer",
    "starbucks": "Starbucks", "mcdonalds": "McDonald's", "chipotle": "Chipotle", "chickfila": "Chick-fil-A",
    "homedepot": "The Home Depot", "thehomedepot": "The Home Depot", "lowes": "Lowe's",
    "acehardware": "Ace Hardware", "menards": "Menards", "harborfreight": "Harbor Freight",
    "shell": "Shell", "exxon": "Exxon", "exxonmobil": "ExxonMobil", "chevron": "Chevron", "valero": "Valero",
    "cvs": "CVS", "cvspharmacy": "CVS", "walgreens": "Walgreens", "amazon": "Amazon", "amazoncom": "Amazon",
    "bestbuy": "Best Buy", "ikea": "IKEA", "panerabread": "Panera Bread", "dunkin": "Dunkin'",
    "samsclub": "Sam's Club", "buceees": "Buc-ee's", "bucees": "Buc-ee's",
}

_SUFFIXES = re.compile(
    r"\b(?:SUPER\s?CENTER|SUPERCENTRE|INC|LLC|L\.L\.C|CORP(?:ORATION)?|CO|COMPANY|LTD)\b\.?"
    r"|\b(?:STORE|ST|NO)\.?\s*#?\s*\d+\b"
    r"|#\s*\d+\b"
    r"|\b\d{3,}\b",
    re.I,
)


def key(name: str) -> str:
    """Comparison key: lowercase letters and digits only."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _fix_ocr_letters(token: str) -> str:
    """In a word that is mostly letters, read digits as the letters OCR
    confuses them with: C0STCO -> COSTCO, SHE1L -> SHELL."""
    letters = sum(c.isalpha() for c in token)
    digits = sum(c.isdigit() for c in token)
    if letters >= 2 and 0 < digits < letters:
        return token.translate(str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B"}))
    return token


def clean(raw: str) -> str:
    """Strip store numbers and corporate suffixes, fix OCR digit/letter swaps."""
    text = " ".join(_fix_ocr_letters(t) for t in raw.split())
    text = text.replace("#", " #")
    text = _SUFFIXES.sub(" ", text)
    text = re.sub(r"[^\w&'\- .]", " ", text)
    return re.sub(r"\s{2,}", " ", text).strip(" -.")


def title(name: str) -> str:
    if not name.isupper() and not name.islower():
        return name  # already mixed case: the user or the receipt chose it
    words = []
    for w in name.lower().split():
        words.append(w if w in {"and", "of", "the", "&"} and words else w[:1].upper() + w[1:])
    return " ".join(words)


def normalize(raw: str | None) -> str | None:
    """A display name with no database: known chain, else cleaned title case."""
    if not raw:
        return None
    cleaned = clean(raw)
    k = key(cleaned)
    if not k:
        return None
    if k in KNOWN:
        return KNOWN[k]
    for known_key, name in KNOWN.items():
        if len(known_key) >= 5 and k.startswith(known_key):
            return name
    return title(cleaned)


def known_merchants(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT merchant FROM receipts WHERE merchant IS NOT NULL AND status = 'confirmed'"
    ).fetchall()
    return [r[0] for r in rows]


def resolve(conn: sqlite3.Connection, raw: str | None) -> str | None:
    """Alias table, then a fuzzy match to a merchant already confirmed, then normalize()."""
    if not raw:
        return None
    for k in (key(raw), key(clean(raw))):
        row = conn.execute("SELECT canonical FROM merchant_aliases WHERE raw_key = ?", (k,)).fetchone()
        if row:
            return row[0]
    candidate = normalize(raw)
    known = known_merchants(conn)
    if candidate and known:
        match = process.extractOne(key(candidate), {m: key(m) for m in known}, scorer=fuzz.ratio, score_cutoff=88)
        if match:
            return match[2]
    return candidate


def learn(conn: sqlite3.Connection, raw: str | None, canonical: str | None) -> None:
    """Remember that this OCR reading means this merchant."""
    if not raw or not canonical:
        return
    now = datetime.now(timezone.utc).isoformat()
    for k in {key(raw), key(clean(raw))}:
        if k:
            conn.execute(
                "INSERT INTO merchant_aliases (raw_key, canonical, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT(raw_key) DO UPDATE SET canonical = excluded.canonical",
                (k, canonical, now),
            )


def fuzzy_find(query: str, merchants: list[str], cutoff: int = 80) -> list[tuple[str, float]]:
    """Merchants that look like the query, typos and all, best first."""
    if not query or not merchants:
        return []
    q = key(query)
    if len(q) < 3:
        return []
    choices = {m: key(m) for m in merchants}
    results = process.extract(q, choices, scorer=fuzz.WRatio, score_cutoff=cutoff, limit=10)
    return [(m, score) for _, score, m in results]
