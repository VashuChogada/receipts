"""Category rules: keywords and regexes on the merchant or the receipt's text.

User rules (priority 100+) beat the seeded defaults. A rule can also suggest a
tag (HSA, Donation), shown in the review modal for the user to accept.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

DEFAULT_CATEGORIES = [
    ("Groceries", "#16a34a"),
    ("Dining", "#ea580c"),
    ("Utilities", "#0891b2"),
    ("Hardware", "#a16207"),
    ("Transport", "#4f46e5"),
    ("Medical", "#dc2626"),
    ("Shopping", "#db2777"),
    ("Entertainment", "#9333ea"),
    ("Travel", "#0284c7"),
    ("Donations", "#059669"),
    ("Other", "#64748b"),
]

DEFAULT_TAGS = [
    ("HSA", "hsa", "#dc2626"),
    ("Donation", "donation", "#059669"),
    ("Warranty", "warranty", "#7c3aed"),
    ("Business", "plain", "#0f766e"),
    ("Tax", "plain", "#b45309"),
]

# (pattern, field, category, tag, priority). Patterns are regexes.
DEFAULT_RULES = [
    (r"walmart|kroger|safeway|whole foods|trader joe|aldi|publix|h-e-b|\bheb\b|costco|sprouts|wegmans|meijer|"
     r"food lion|albertsons|instacart|grocery|supermarket|sam's club|market\b", "merchant", "Groceries", None, 10),
    (r"starbucks|mcdonald|chipotle|subway|taco|pizza|diner|cafe|café|coffee|restaurant|grill|doordash|uber eats|"
     r"grubhub|kitchen|bistro|burger|bakery|chick-fil-a|panera|wendy|dunkin|sushi|bbq|deli", "merchant", "Dining", None, 10),
    (r"electric|energy|water|utility|utilities|comcast|xfinity|at&t|verizon|t-mobile|spectrum|internet|atmos",
     "merchant", "Utilities", None, 10),
    (r"home depot|lowe's|lowes|ace hardware|menards|harbor freight|true value|hardware", "merchant", "Hardware", None, 10),
    (r"shell|exxon|chevron|\bbp\b|valero|mobil|citgo|sunoco|circle k|buc-ee|uber|lyft|parking|toll|fuel|"
     r"gas station|\b76\b|quiktrip|qt\b", "merchant", "Transport", None, 10),
    (r"cvs|walgreens|pharmacy|clinic|hospital|dental|dentist|medical|health|optometr|vision|urgent care|labcorp|"
     r"quest diagnostics|pediatric|physician|\bmd\b|dds\b", "merchant", "Medical", "HSA", 10),
    (r"target|amazon|best buy|ikea|macy|kohl|tj maxx|marshalls|\bross\b|old navy|nordstrom|etsy|ebay",
     "merchant", "Shopping", None, 10),
    (r"\bamc\b|cinemark|netflix|spotify|theat(er|re)|cinema|steam|ticketmaster|museum|bowling",
     "merchant", "Entertainment", None, 10),
    (r"airline|hotel|marriott|hilton|hyatt|airbnb|\bdelta\b|united airlines|southwest|american airlines|expedia",
     "merchant", "Travel", None, 10),
    (r"donation receipt|tax[- ]deductible|no goods or services|501\s*\(c\)|charitable contribution|"
     r"thank you for your (generous )?(gift|donation)", "text", "Donations", "Donation", 8),
    (r"\b(rx|prescription|copay|co-pay|patient)\b|hsa eligible|fsa eligible", "text", "Medical", "HSA", 5),
    (r"warranty|protection plan", "text", None, "Warranty", 5),
]


@dataclass
class Rule:
    id: int | None
    pattern: str
    field: str
    is_regex: bool
    category: str | None
    tag: str | None
    priority: int

    def matches(self, merchant: str, text: str) -> bool:
        target = merchant if self.field == "merchant" else text
        if not target:
            return False
        if self.is_regex:
            try:
                return re.search(self.pattern, target, re.I) is not None
            except re.error:
                return False
        return self.pattern.lower() in target.lower()


def seed(conn: sqlite3.Connection) -> None:
    """First run only: the default categories, tags and rules."""
    now = datetime.now(timezone.utc).isoformat()
    if not conn.execute("SELECT 1 FROM categories LIMIT 1").fetchone():
        conn.executemany(
            "INSERT INTO categories (name, color, sort) VALUES (?, ?, ?)",
            [(name, color, i) for i, (name, color) in enumerate(DEFAULT_CATEGORIES)],
        )
    if not conn.execute("SELECT 1 FROM tags LIMIT 1").fetchone():
        conn.executemany("INSERT INTO tags (name, kind, color) VALUES (?, ?, ?)", DEFAULT_TAGS)
    if not conn.execute("SELECT 1 FROM rules WHERE source = 'default' LIMIT 1").fetchone():
        conn.executemany(
            "INSERT INTO rules (pattern, field, is_regex, category, tag, priority, source, created_at) "
            "VALUES (?, ?, 1, ?, ?, ?, 'default', ?)",
            [(p, f, c, t, pr, now) for p, f, c, t, pr in DEFAULT_RULES],
        )
    conn.commit()


def load_rules(conn: sqlite3.Connection) -> list[Rule]:
    rows = conn.execute(
        "SELECT id, pattern, field, is_regex, category, tag, priority FROM rules ORDER BY priority DESC, id DESC"
    ).fetchall()
    return [Rule(r["id"], r["pattern"], r["field"], bool(r["is_regex"]), r["category"], r["tag"], r["priority"]) for r in rows]


def classify(rules: list[Rule], merchant: str | None, text: str | None) -> tuple[str | None, list[str], int | None]:
    """The category from the highest-priority matching rule, every tag any
    matching rule suggests, and the id of the rule that set the category."""
    category = None
    rule_id = None
    tags: list[str] = []
    for rule in rules:
        if not rule.matches(merchant or "", text or ""):
            continue
        if category is None and rule.category:
            category, rule_id = rule.category, rule.id
        if rule.tag and rule.tag not in tags:
            tags.append(rule.tag)
    return category, tags, rule_id


def remember_merchant(conn: sqlite3.Connection, merchant: str, category: str) -> None:
    """'Always file <merchant> under <category>': a user rule on the exact name."""
    now = datetime.now(timezone.utc).isoformat()
    pattern = r"^" + re.escape(merchant) + r"$"
    existing = conn.execute(
        "SELECT id FROM rules WHERE source = 'user' AND field = 'merchant' AND pattern = ?", (pattern,)
    ).fetchone()
    if existing:
        conn.execute("UPDATE rules SET category = ? WHERE id = ?", (category, existing[0]))
    else:
        conn.execute(
            "INSERT INTO rules (pattern, field, is_regex, category, tag, priority, source, created_at) "
            "VALUES (?, 'merchant', 1, ?, NULL, 200, 'user', ?)",
            (pattern, category, now),
        )
