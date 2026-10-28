"""Plain-English search: "costco over $50 last month" -> filters + leftover text.

Rule-based and offline. Each recognized phrase is taken out of the query and
becomes a filter; the UI shows them as chips the user can remove. Whatever is
left over is free text for the hybrid search.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from rapidfuzz import fuzz

from . import merchants as merchant_mod

_MONTH_NAMES = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9, "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
_MONTH = r"(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)"
_NUM = r"\$?\s?(\d+(?:,\d{3})*(?:\.\d{1,2})?)"
_DATE = rf"(?:{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?|\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?|\d{{4}}-\d{{2}}-\d{{2}})"

_PAYMENTS = {
    "visa": "Visa", "mastercard": "Mastercard", "master card": "Mastercard", "amex": "Amex",
    "american express": "Amex", "discover": "Discover", "debit": "Debit", "cash": "Cash",
    "apple pay": "Apple Pay", "google pay": "Google Pay",
}

_CATEGORY_SYNONYMS = {
    "grocery": "Groceries", "groceries": "Groceries", "food shopping": "Groceries",
    "dining": "Dining", "restaurant": "Dining", "restaurants": "Dining", "eating out": "Dining",
    "takeout": "Dining", "fuel": "Transport", "gas station": "Transport", "transport": "Transport",
    "transportation": "Transport", "medical": "Medical", "doctor": "Medical", "pharmacy": "Medical",
    "utility": "Utilities", "utilities": "Utilities", "bills": "Utilities", "hardware": "Hardware",
    "shopping": "Shopping", "travel": "Travel", "entertainment": "Entertainment",
    "donations": "Donations", "charity": "Donations",
}
_TAG_SYNONYMS = {
    "hsa": "HSA", "fsa": "HSA", "donation": "Donation", "donations": "Donation",
    "tax deductible": "Donation", "charitable": "Donation", "warranty": "Warranty", "warranties": "Warranty",
}

_STOPWORDS = {
    "show", "me", "find", "all", "my", "the", "a", "an", "receipts", "receipt", "from", "at", "in", "on",
    "for", "of", "to", "with", "what", "did", "i", "we", "spend", "spent", "how", "much", "paid", "pay",
    "purchases", "purchase", "bought", "buy", "stuff", "things", "and", "or", "any", "where", "when", "that",
    "was", "were", "is", "are", "list", "get", "by", "using", "used", "via", "items",
}


@dataclass
class Chip:
    key: str
    label: str


@dataclass
class Query:
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
    text: str = ""
    chips: list[Chip] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _fmt(d: date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def _money(s: str) -> float:
    return float(s.replace(",", ""))


def _month_range(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _parse_one_date(s: str, today: date) -> date | None:
    s = s.strip().lower().replace(",", "")
    m = re.fullmatch(rf"{_MONTH}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:\s+(\d{{4}}))?", s)
    if m:
        month = _MONTH_NAMES[m.group(1)]
        year = int(m.group(3)) if m.group(3) else today.year
        try:
            d = date(year, month, int(m.group(2)))
        except ValueError:
            return None
        if not m.group(3) and d > today:
            d = d.replace(year=year - 1)
        return d
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", s)
    if m:
        year = int(m.group(3)) if m.group(3) else today.year
        if year < 100:
            year += 2000
        try:
            return date(year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


class _Parser:
    def __init__(self, text: str, today: date):
        self.s = " " + text.lower().strip() + " "
        self.today = today
        self.q = Query()

    def take(self, pattern: str, handler) -> None:
        """Run handler on each match; remove the matches it accepts."""
        def repl(m: re.Match) -> str:
            return " " if handler(m) is not False else m.group(0)

        self.s = re.sub(pattern, repl, self.s)

    def set_dates(self, start: date | None, end: date | None, label: str) -> None:
        self.q.date_from = start.isoformat() if start else None
        self.q.date_to = end.isoformat() if end else None
        self.q.chips.append(Chip("date", label))


def parse(
    text: str,
    today: date | None = None,
    merchants: list[str] | None = None,
    categories: list[str] | None = None,
    tags: list[str] | None = None,
    usernames: list[str] | None = None,
    current_user: str | None = None,
) -> Query:
    today = today or date.today()
    p = _Parser(text or "", today)
    q = p.q
    categories = categories or []
    tags = tags or []
    usernames = usernames or []

    # Dates first, so "between jan 1 and mar 3" isn't read as an amount range.
    def between_dates(m):
        a, b = _parse_one_date(m.group("a"), today), _parse_one_date(m.group("b"), today)
        if not a or not b:
            return False
        lo, hi = min(a, b), max(a, b)
        p.set_dates(lo, hi, f"{_fmt(lo)} – {_fmt(hi)}")
        return True

    p.take(rf"\b(?:between|from)\s+(?P<a>{_DATE})\s+(?:and|to|-)\s+(?P<b>{_DATE})\b", between_dates)

    def since(m):
        d = _parse_one_date(m.group(2), today)
        if not d:
            return False
        if m.group(1) in ("since", "after"):
            p.set_dates(d if m.group(1) == "since" else d + timedelta(days=1), None, f"{m.group(1)} {_fmt(d)}")
        else:
            p.set_dates(None, d - timedelta(days=1), f"before {_fmt(d)}")
        return True

    p.take(rf"\b(since|after|before)\s+({_DATE})\b", since)

    # Amounts.
    def amount_between(m):
        lo, hi = sorted((_money(m.group(1)), _money(m.group(2))))
        q.min_total, q.max_total = lo, hi
        q.chips.append(Chip("amount", f"${lo:g} – ${hi:g}"))

    p.take(rf"\bbetween\s+{_NUM}\s+(?:and|to|-)\s+{_NUM}\b", amount_between)

    def amount_min(m):
        q.min_total = _money(m.group(1))
        q.chips.append(Chip("min_total", f"≥ ${q.min_total:g}"))

    p.take(rf"(?:\b(?:over|above|more than|greater than|at least|min(?:imum)?)\s+|>\s*=?\s*){_NUM}(?!\d)", amount_min)

    def amount_max(m):
        q.max_total = _money(m.group(1))
        q.chips.append(Chip("max_total", f"≤ ${q.max_total:g}"))

    p.take(rf"(?:\b(?:under|below|less than|at most|max(?:imum)?|cheaper than)\s+|<\s*=?\s*){_NUM}(?!\d)", amount_max)

    def amount_exact(m):
        v = _money(m.group(1))
        q.min_total = q.max_total = v
        q.chips.append(Chip("amount", f"${v:,.2f}"))

    p.take(r"\$\s?(\d+(?:,\d{3})*(?:\.\d{1,2})?)(?!\d)", amount_exact)

    # Relative dates.
    t = today
    week_start = t - timedelta(days=t.weekday())
    first_this_month = t.replace(day=1)
    last_month_end = first_this_month - timedelta(days=1)
    relative = [
        (r"today", (t, t), "today"),
        (r"yesterday", (t - timedelta(days=1), t - timedelta(days=1)), "yesterday"),
        (r"this week", (week_start, t), "this week"),
        (r"last week", (week_start - timedelta(days=7), week_start - timedelta(days=1)), "last week"),
        (r"this month", (first_this_month, t), "this month"),
        (r"last month", (last_month_end.replace(day=1), last_month_end), "last month"),
        (r"(?:this year|ytd|year to date)", (date(t.year, 1, 1), t), f"{t.year} to date"),
        (r"last year", (date(t.year - 1, 1, 1), date(t.year - 1, 12, 31)), str(t.year - 1)),
    ]
    for pattern, (start, end), label in relative:
        if q.date_from or q.date_to:
            break
        p.take(rf"\b{pattern}\b", lambda m, s=start, e=end, lb=label: p.set_dates(s, e, lb))

    def past_n(m):
        n, unit = int(m.group(1)), m.group(2)
        days = n * {"day": 1, "week": 7, "month": 30, "year": 365}[unit]
        p.set_dates(t - timedelta(days=days), t, f"last {n} {unit}s")

    if not (q.date_from or q.date_to):
        p.take(r"\b(?:past|last)\s+(\d+)\s+(day|week|month|year)s?\b", past_n)

    def quarter(m):
        n = int(m.group(1))
        year = int(m.group(2)) if m.group(2) else t.year
        start = date(year, 3 * n - 2, 1)
        if not m.group(2) and start > t:
            year -= 1
            start = date(year, 3 * n - 2, 1)
        end = _month_range(year, 3 * n)[1]
        p.set_dates(start, end, f"Q{n} {year}")

    if not (q.date_from or q.date_to):
        p.take(r"\bq([1-4])(?:\s+(\d{4}))?\b", quarter)

    def month_year(m):
        month = _MONTH_NAMES[m.group(1)]
        if m.group(2):
            year = int(m.group(2))
        else:
            year = t.year if month <= t.month else t.year - 1
        start, end = _month_range(year, month)
        p.set_dates(start, end, f"{start:%B %Y}")

    if not (q.date_from or q.date_to):
        # "may" is also a verb; only take it with a year or "in".
        p.take(rf"\b(?:in\s+)?{_MONTH}\.?(?:\s+(\d{{4}}))?\b(?<!\bmay)(?<!\bmar)|\bin\s+(may|mar)(?:\s+(\d{{4}}))?\b|\b(may|mar)\s+(\d{{4}})\b",
               lambda m: month_year(_Pick(m)))

    def year_only(m):
        year = int(m.group(1))
        p.set_dates(date(year, 1, 1), date(year, 12, 31), str(year))

    if not (q.date_from or q.date_to):
        p.take(r"\b(?:in\s+)?(20\d{2})\b", year_only)

    def exact_date(m):
        d = _parse_one_date(m.group(1), today)
        if not d:
            return False
        p.set_dates(d, d, _fmt(d))

    if not (q.date_from or q.date_to):
        p.take(rf"\b(?:on\s+)?(\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?|\d{{4}}-\d{{2}}-\d{{2}})\b", exact_date)

    # Payment.
    def card(m):
        q.card_last4 = m.group(1)
        q.chips.append(Chip("card_last4", f"card ••{q.card_last4}"))

    p.take(r"\b(?:card|ending(?:\s+in)?|x|\*{1,4})\s*(\d{4})\b", card)
    for phrase, method in _PAYMENTS.items():
        if q.payment_method:
            break

        def pay(m, method=method):
            q.payment_method = method
            q.chips.append(Chip("payment_method", method))

        p.take(rf"\b(?:paid\s+(?:with|by)\s+|by\s+|with\s+)?{phrase}\b", pay)

    # Status and HSA reimbursement.
    def unreimbursed(m):
        q.reimbursed = False
        if "HSA" not in q.tags:
            q.tags.append("HSA")
        q.chips.append(Chip("reimbursed", "not reimbursed"))

    p.take(r"\b(?:unreimbursed|not\s+(?:yet\s+)?reimbursed)\b", unreimbursed)

    def reimbursed(m):
        q.reimbursed = True
        if "HSA" not in q.tags:
            q.tags.append("HSA")
        q.chips.append(Chip("reimbursed", "reimbursed"))

    p.take(r"\breimbursed\b", reimbursed)

    def needs_review(m):
        q.status = "review"
        q.chips.append(Chip("status", "needs review"))

    p.take(r"\b(?:needs?\s+review|to\s+review|unconfirmed|pending|unreviewed)\b", needs_review)

    # People.
    if current_user:
        def mine(m):
            q.created_by = current_user
            q.chips.append(Chip("created_by", "mine"))

        p.take(r"\b(?:mine|my own|added by me|i added)\b", mine)
    for name in usernames:
        def by_user(m, name=name):
            q.created_by = name
            q.chips.append(Chip("created_by", name))

        p.take(rf"\b(?:{re.escape(name.lower())}'s|added by {re.escape(name.lower())})\b", by_user)

    # Tags, then categories (longest names first so "gas station" beats "gas").
    tag_names = {t.lower(): t for t in tags}
    tag_names.update({k: v for k, v in _TAG_SYNONYMS.items() if v in tags or not tags})
    for phrase in sorted(tag_names, key=len, reverse=True):
        def add_tag(m, name=tag_names[phrase]):
            if name not in q.tags:
                q.tags.append(name)
                q.chips.append(Chip("tag", name))

        p.take(rf"\b{re.escape(phrase)}\b", add_tag)

    cat_names = {c.lower(): c for c in categories}
    for c in categories:
        if c.lower().endswith("s"):
            cat_names.setdefault(c.lower()[:-1], c)
    cat_names.update({k: v for k, v in _CATEGORY_SYNONYMS.items() if v in categories or not categories})
    for phrase in sorted(cat_names, key=len, reverse=True):
        if q.category:
            break

        def set_cat(m, name=cat_names[phrase]):
            q.category = name
            q.chips.append(Chip("category", name))

        p.take(rf"\b{re.escape(phrase)}\b", set_cat)

    # Merchants: the best fuzzy match among 1-3 word runs of what's left.
    words = [w for w in re.findall(r"[a-z0-9&'\-]+", p.s) if w not in _STOPWORDS]
    if merchants and words:
        best: tuple[float, str, str] | None = None
        mkeys = {m: merchant_mod.key(m) for m in merchants}
        for n in (3, 2, 1):
            for i in range(len(words) - n + 1):
                phrase = " ".join(words[i : i + n])
                pk = merchant_mod.key(phrase)
                if len(pk) < 3:
                    continue
                for m, mk in mkeys.items():
                    score = fuzz.ratio(pk, mk)
                    # "home depot" for "The Home Depot": a whole-word part of the name.
                    if len(pk) >= 5 and pk in mk and len(pk) >= len(mk) / 2:
                        score = max(score, 90 + min(len(pk), 10) / 2)
                    if score >= 85 and (best is None or score > best[0]):
                        best = (score, m, phrase)
        if best:
            q.merchant = best[1]
            q.chips.append(Chip("merchant", best[1]))
            p.s = re.sub(r"\b" + r"\W+".join(map(re.escape, best[2].split())) + r"\b", " ", p.s, count=1)
            words = [w for w in re.findall(r"[a-z0-9&'\-]+", p.s) if w not in _STOPWORDS]

    q.text = " ".join(words)
    return q


class _Pick:
    """Normalize the three alternatives of the month regex to (month, year)."""

    def __init__(self, m: re.Match):
        g = m.groups()
        if g[0]:
            self._g = (g[0], g[1])
        elif g[2]:
            self._g = (g[2], g[3])
        else:
            self._g = (g[4], g[5])

    def group(self, i: int):
        return self._g[i - 1]
