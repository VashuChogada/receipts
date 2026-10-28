"""Turns a receipt's OCR text into fields. Pure functions: no I/O, no DB.

Receipts are noisy, so every field is best-effort and the user confirms
them in the review modal. Each rule here has a case in tests/test_parse.py.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

# An amount with two decimals: 12.34, 1,234.56, $ 5.00, -3.00 and OCR's 12,34.
# Not 8.25% (a tax rate) and not part of a longer number.
AMOUNT_RE = re.compile(
    r"(?<![\d.,])(-)?\$?\s?(\d{1,3}(?:,\d{3})+|\d+)\s?[.,]\s?(\d{2})(?![\d%])(?!\s*%)"
)

_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "SEPT": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
_MONTH_ALT = r"(JAN|FEB|MAR|APR|MAY|JUNE?|JULY?|AUG|SEPT?|OCT|NOV|DEC)[A-Z]*\.?"

_NUMERIC_DATE = re.compile(r"(?<!\d)(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4}|\d{2})(?!\d)")
_ISO_DATE = re.compile(r"(?<!\d)(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})(?!\d)")
_NAMED_DATE = re.compile(rf"\b{_MONTH_ALT}\s+(\d{{1,2}})(?:ST|ND|RD|TH)?,?\s+(\d{{4}}|\d{{2}})\b")
_NAMED_DATE_DMY = re.compile(rf"\b(\d{{1,2}})[\s\-]+{_MONTH_ALT}[,\s\-]+(\d{{4}}|\d{{2}})\b")
# MMDDYYYY run together, when faint slashes didn't print or scan: only trusted
# right before a time, where a barcode or reference number wouldn't be.
_COMPACT_DATE = re.compile(r"(?<!\d)(\d{2})(\d{2})(20\d{2})(?=\s+\d{1,2}:\d{2})")
_TIME = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?::\d{2})?\s*([AP])?\.?\s?M?\.?(?![\d])")

# Keyword classes, matched on the uppercased line. OCR reads O as 0 often
# enough that TOTAL is spelled T[O0]TAL throughout.
_SUBTOTAL = re.compile(r"\bSUB\s*-?\s*T[O0]TAL\b|\bSUBTTL\b|\bSUB\s*TTL\b|\bMERCHANDISE\s+T[O0]TAL\b")
_TAX = re.compile(r"\b(?:SALES\s+)?TAX\b|\bTX\b|\bHST\b|\bGST\b")
_GRAND = re.compile(r"\bGRAND\s+T[O0]TAL\b|\bBAL(?:ANCE)?\s+DUE\b|\bAMOUNT\s+DUE\b|\bAMT\s+DUE\b|\bT[O0]TAL\s+DUE\b")
_TOTAL = re.compile(r"\bT[O0]TAL\b|\bTTL\b")
_NOT_TOTAL = re.compile(
    r"SAVINGS|SAVED|DISCOUNT|ITEMS|ITEM\s+COUNT|QTY|POINTS|REWARD|COUPON|TIP\s+GUIDE|"
    r"\bTAX\b|ELIGIBLE|\bPREV|\bYOU\s+SAVED"
)
_TENDER = re.compile(r"\bCHANGE\b|\bCASH\b|\bTEND|\bTENDERED\b|\bPAID\b|\bVISA\b|\bMASTERCARD\b|\bAMEX\b|\bDEBIT\b|\bCREDIT\b")
_NOT_ITEM = re.compile(
    r"T[O0]TAL|\bTAX\b|\bTX\b|CHANGE|\bCASH\b|TEND|\bVISA\b|MASTER\s?CARD|\bAMEX\b|DISCOVER|"
    r"\bDEBIT\b|\bCREDIT\b|BALANCE|\bDUE\b|SAVINGS|YOU\s+SAVED|AUTH|APPROV|\bREF\b|ACCOUNT|\bCARD\b|"
    r"\bPAID\b|\bTIP\b|GRATUITY|\bAPPLE\s+PAY|GOOGLE\s+PAY|\bPAYMENT\b"
)

_PAYMENTS = [
    ("Apple Pay", re.compile(r"\bAPPLE\s*PAY\b")),
    ("Google Pay", re.compile(r"\bGOOGLE\s*PAY\b|\bGPAY\b")),
    ("Visa", re.compile(r"\bVISA\b")),
    ("Mastercard", re.compile(r"\bMASTER\s?CARD\b|\bMC\b|\bMCARD\b")),
    ("Amex", re.compile(r"\bAMEX\b|\bAMERICAN\s+EXPRESS\b")),
    ("Discover", re.compile(r"\bDISCOVER\b")),
    ("Debit", re.compile(r"\bDEB[I1L]T\b")),
    ("Credit", re.compile(r"\bCREDIT\s+CARD\b|\bCREDIT\b")),
    ("Check", re.compile(r"\bCHECK\s+(?:TEND|PAYMENT|#)")),
    ("Cash", re.compile(r"\bCASH\b(?!\s*(?:BACK|IER|REGISTER))")),
]
_LAST4 = [
    re.compile(r"(?:[X*#•]{2,}[\s-]*){1,4}(\d{4})\b"),
    re.compile(r"\bENDING\s+(?:IN\s+)?(\d{4})\b"),
    re.compile(r"\b(?:ACCOUNT|ACCT|CARD)\s*(?:NO\.?|NUMBER|#)?\s*:?\s*[X*#]*\s*(\d{4})\b"),
]

_PHONE = re.compile(r"\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}")
_STREET = re.compile(
    r"^\s*\d+\s+.*\b(ST|STREET|AVE|AVENUE|RD|ROAD|BLVD|DR|DRIVE|LN|LANE|HWY|HIGHWAY|PKWY|WAY|CT|PL|PLAZA|SUITE|STE)\b\.?",
    re.I,
)
_CITY_STATE_ZIP = re.compile(r"\b[A-Z][A-Za-z .'-]+,?\s+[A-Z]{2}\s+\d{5}(?:-\d{4})?\b")
_MERCHANT_NOISE = re.compile(
    r"WELCOME|THANK|RECEIPT|INVOICE|STORE\s*#|STORE\s+NO|\bTEL\b|PHONE|WWW\.|HTTP|\.COM\b|CASHIER|"
    r"REGISTER|\bTRANS|\bORDER\b|^\s*#|OPEN\s+\d|HOURS|MANAGER|SURVEY|\bCOPY\b",
    re.I,
)


@dataclass
class LineItem:
    description: str
    amount: float
    qty: float | None = None
    unit_price: float | None = None


@dataclass
class Parsed:
    merchant: str | None = None
    txn_date: str | None = None  # ISO yyyy-mm-dd
    txn_time: str | None = None  # 24h HH:MM
    subtotal: float | None = None
    tax: float | None = None
    total: float | None = None
    payment_method: str | None = None
    card_last4: str | None = None
    line_items: list[LineItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def to_amount(match: re.Match) -> float | None:
    sign, whole, cents = match.group(1), match.group(2), match.group(3)
    try:
        value = Decimal(whole.replace(",", "") + "." + cents)
    except InvalidOperation:
        return None
    return float(-value if sign else value)


def amounts_in(line: str) -> list[float]:
    out = []
    for m in AMOUNT_RE.finditer(line):
        value = to_amount(m)
        if value is not None:
            out.append(value)
    return out


# A token shaped like an amount with letters OCR mistakes for digits in it:
# "@.00", "1O.5O", "S.99". It needs at least one real digit or the @.
_AMOUNTISH = re.compile(r"(?<![\w.])(\$?)([\d@OoIlS]{1,7})([.,])([\d@OoIlS]{2})(?![\w.])")
_DIGIT_FIX = str.maketrans({"@": "0", "O": "0", "o": "0", "I": "1", "l": "1", "S": "5"})


def _fix_amount_digits(line: str) -> str:
    def repl(m: re.Match) -> str:
        body = m.group(2) + m.group(4)
        if not re.search(r"[\d@]", body) or body.isalpha():
            return m.group(0)
        return f"{m.group(1)}{m.group(2).translate(_DIGIT_FIX)}{m.group(3)}{m.group(4).translate(_DIGIT_FIX)}"

    return _AMOUNTISH.sub(repl, line)


def _clean_lines(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = _fix_amount_digits(re.sub(r"[ \t]+", " ", raw).strip())
        if line:
            lines.append(line)
    return lines


def _year(y: str) -> int:
    n = int(y)
    return 2000 + n if n < 100 else n


def _valid_date(y: int, m: int, d: int, today: date) -> date | None:
    try:
        value = date(y, m, d)
    except ValueError:
        return None
    if value.year < 2000 or value > today + timedelta(days=7):
        return None
    return value


def parse_date(text: str, date_order: str = "MDY", today: date | None = None) -> str | None:
    today = today or date.today()
    # OCR reads the O of OCT as a zero: 11-0CT-2026.
    upper = re.sub(r"(?<![A-Z0-9])0(CT|CTOBER)(?![A-Z])", r"O\1", text.upper())
    candidates: list[tuple[int, date]] = []

    for m in _COMPACT_DATE.finditer(upper):
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        month, day = (a, b) if date_order == "MDY" else (b, a)
        value = _valid_date(y, month, day, today)
        if value:
            candidates.append((m.start(), value))

    for m in _ISO_DATE.finditer(upper):
        value = _valid_date(int(m.group(1)), int(m.group(2)), int(m.group(3)), today)
        if value:
            candidates.append((m.start(), value))

    for m in _NUMERIC_DATE.finditer(upper):
        a, b, y = int(m.group(1)), int(m.group(2)), _year(m.group(3))
        month, day = (a, b) if date_order == "MDY" else (b, a)
        # A first number over 12 can only be a day, whatever the locale.
        if month > 12 and day <= 12:
            month, day = day, month
        value = _valid_date(y, month, day, today)
        if value:
            candidates.append((m.start(), value))

    for m in _NAMED_DATE.finditer(upper):
        month = _MONTHS.get(m.group(1)[:4] if m.group(1).startswith("SEPT") else m.group(1)[:3])
        if month:
            value = _valid_date(_year(m.group(3)), month, int(m.group(2)), today)
            if value:
                candidates.append((m.start(), value))

    for m in _NAMED_DATE_DMY.finditer(upper):
        month = _MONTHS.get(m.group(2)[:3])
        if month:
            value = _valid_date(_year(m.group(3)), month, int(m.group(1)), today)
            if value:
                candidates.append((m.start(), value))

    if not candidates:
        return None
    # The first date printed is the transaction date; return-by dates and
    # survey deadlines come later on the slip.
    candidates.sort(key=lambda c: c[0])
    return candidates[0][1].isoformat()


def parse_time(text: str) -> str | None:
    for m in _TIME.finditer(text.upper()):
        hour, minute, half = int(m.group(1)), int(m.group(2)), m.group(3)
        if minute > 59:
            continue
        if half:
            if not 1 <= hour <= 12:
                continue
            hour = hour % 12 + (12 if half == "P" else 0)
        elif hour > 23:
            continue
        return f"{hour:02d}:{minute:02d}"
    return None


def _line_amount(lines: list[str], i: int) -> float | None:
    """The amount for a labelled line: its last amount, or the next line's when
    OCR split the label and value apart."""
    found = amounts_in(lines[i])
    if found:
        return found[-1]
    if i + 1 < len(lines):
        nxt = lines[i + 1]
        if re.fullmatch(r"[\s$\-]*" + AMOUNT_RE.pattern + r"[\s A-Z]{0,3}", nxt):
            found = amounts_in(nxt)
            if found:
                return found[-1]
    return None


def parse_amounts(lines: list[str]) -> tuple[float | None, float | None, float | None]:
    subtotal = tax = None
    grand: list[float] = []
    totals: list[float] = []
    tax_total = 0.0
    tax_seen = tax_locked = False

    for i, line in enumerate(lines):
        up = line.upper()
        if _SUBTOTAL.search(up):
            value = _line_amount(lines, i)
            if value is not None and subtotal is None:
                subtotal = value
            continue
        if re.search(r"\bT[O0]TAL\s+(?:SALES\s+)?TAX\b", up):
            value = _line_amount(lines, i)
            if value is not None:
                tax_total, tax_seen = value, True
                tax_locked = True
            continue
        if _TAX.search(up) and not _TOTAL.search(up) and not _GRAND.search(up):
            value = _line_amount(lines, i)
            # Several tax lines (state + local) add up, unless a TOTAL TAX
            # line already gave the sum.
            if value is not None and value >= 0 and not tax_locked:
                tax_total += value
                tax_seen = True
            continue
        if _GRAND.search(up):
            value = _line_amount(lines, i)
            if value is not None:
                grand.append(value)
            continue
        if _TOTAL.search(up) and not _NOT_TOTAL.search(up):
            value = _line_amount(lines, i)
            if value is not None:
                totals.append(value)

    if tax_seen:
        tax = round(tax_total, 2)

    total = max(grand) if grand else (max(totals) if totals else None)

    if total is None and subtotal is not None and tax is not None:
        total = round(subtotal + tax, 2)
    if total is None:
        # No label survived OCR: take the largest amount in the bottom
        # two-thirds that isn't cash handed over or change given back.
        start = len(lines) // 3
        pool = [
            a
            for line in lines[start:]
            if not re.search(r"\bCHANGE\b|\bCASH\b|TEND", line.upper())
            for a in amounts_in(line)
        ]
        total = max(pool) if pool else None
    if tax is None and subtotal is not None and total is not None:
        diff = round(total - subtotal, 2)
        if 0 < diff <= subtotal * 0.2:
            tax = diff
    if subtotal is None and total is not None and tax is not None and tax < total:
        subtotal = round(total - tax, 2)
    return subtotal, tax, total


def parse_payment(lines: list[str]) -> tuple[str | None, str | None]:
    upper = "\n".join(lines).upper()
    method = None
    for name, pattern in _PAYMENTS:
        if pattern.search(upper):
            method = name
            break
    last4 = None
    for pattern in _LAST4:
        m = pattern.search(upper)
        if m:
            last4 = m.group(1)
            break
    return method, last4


def _is_merchant_candidate(line: str) -> bool:
    letters = sum(c.isalpha() for c in line)
    if letters < 3 or letters < len(line) * 0.5:
        return False
    if _PHONE.search(line) or _STREET.search(line) or _CITY_STATE_ZIP.search(line.upper()):
        return False
    if _MERCHANT_NOISE.search(line):
        return False
    if parse_date(line, today=date(2100, 1, 1)) or _TIME.search(line):
        return False
    if amounts_in(line):
        return False
    return True


def parse_merchant(lines: list[str]) -> str | None:
    for line in lines[:8]:
        if _is_merchant_candidate(line):
            name = re.sub(r"^[^A-Za-z0-9&']+|[^A-Za-z0-9&'.)]+$", "", line)
            name = re.sub(r"\s{2,}", " ", name)
            if len(name) >= 3:
                return name
    return None


_ITEM_RE = re.compile(
    r"^(?P<desc>.*?[A-Za-z]{2}.*?)\s+"
    r"(?:(?P<qty>\d+(?:\.\d+)?)\s*(?:@|X|x|\*)\s*\$?(?P<unit>\d+[.,]\d{2})\s+)?"
    r"(?P<amt>-?\$?\d+[.,]\d{2})\s*(?:[A-Z]{1,2}|\*)?\s*$"
)


def parse_line_items(lines: list[str]) -> list[LineItem]:
    items: list[LineItem] = []
    for line in lines:
        up = line.upper()
        if _SUBTOTAL.search(up) or _GRAND.search(up) or (_TOTAL.search(up) and not _NOT_TOTAL.search(up)):
            break
        if _NOT_ITEM.search(up) or _PHONE.search(line):
            continue
        m = _ITEM_RE.match(line)
        if not m:
            continue
        # Drop UPC/SKU numbers and the one-letter tax flags printed beside them.
        desc = re.sub(r"(?:^|\s+)\d{6,}(?=\s|$)", " ", m.group("desc"))
        desc = re.sub(r"\s+[A-Z]$", "", desc.strip()).strip(" .:-")
        if len(desc) < 2:
            continue
        amount = float(m.group("amt").replace("$", "").replace(",", "."))
        qty = float(m.group("qty")) if m.group("qty") else None
        unit = float(m.group("unit").replace(",", ".")) if m.group("unit") else None
        items.append(LineItem(description=desc, amount=amount, qty=qty, unit_price=unit))
    return items


def parse_receipt(text: str, date_order: str = "MDY", today: date | None = None) -> Parsed:
    lines = _clean_lines(text)
    subtotal, tax, total = parse_amounts(lines)
    method, last4 = parse_payment(lines)
    return Parsed(
        merchant=parse_merchant(lines),
        txn_date=parse_date(text, date_order, today),
        txn_time=parse_time(text),
        subtotal=subtotal,
        tax=tax,
        total=total,
        payment_method=method,
        card_last4=last4,
        line_items=parse_line_items(lines[1:]),
    )
