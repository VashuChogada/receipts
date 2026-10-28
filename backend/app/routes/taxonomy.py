"""Categories, tags, rules and merchant aliases."""

from __future__ import annotations

import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import categorize, records
from ..auth import User, current_user
from ..db import Conn, get_db
from ..records import now

router = APIRouter(prefix="/api", tags=["taxonomy"])

COLOR = r"^#[0-9a-fA-F]{6}$"


class Category(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    color: str = Field(default="#64748b", pattern=COLOR)
    sort: int = 100


class CategoryPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    color: str | None = Field(default=None, pattern=COLOR)
    sort: int | None = None


@router.get("/categories")
def list_categories(_: User = Depends(current_user), conn: Conn = Depends(get_db)):
    rows = conn.execute(
        "SELECT c.name, c.color, c.sort, (SELECT COUNT(*) FROM receipts r WHERE r.category = c.name) AS count "
        "FROM categories c ORDER BY c.sort, c.name COLLATE NOCASE"
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/categories")
def create_category(body: Category, _: User = Depends(current_user), conn: Conn = Depends(get_db)):
    try:
        conn.execute("INSERT INTO categories (name, color, sort) VALUES (?, ?, ?)", (body.name.strip(), body.color, body.sort))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "That category exists")
    conn.commit()
    return body


def _refile(conn: Conn, where: str, params: tuple) -> None:
    """Receipts whose folder depends on a renamed category or tag: move them
    and rewrite their details files."""
    for (rid,) in conn.execute(f"SELECT id FROM receipts WHERE {where}", params).fetchall():
        records.relocate(conn, rid)
        records.reindex_one(conn, rid)
        records.save_sidecar(conn, rid)


@router.patch("/categories/{name}")
def update_category(name: str, body: CategoryPatch, user: User = Depends(current_user), conn: Conn = Depends(get_db)):
    row = conn.execute("SELECT name FROM categories WHERE name = ?", (name,)).fetchone()
    if not row:
        raise HTTPException(404, "No such category")
    old = row[0]
    if body.color:
        conn.execute("UPDATE categories SET color = ? WHERE name = ?", (body.color, old))
    if body.sort is not None:
        conn.execute("UPDATE categories SET sort = ? WHERE name = ?", (body.sort, old))
    if body.name and body.name.strip() != old:
        new = body.name.strip()
        if conn.execute("SELECT 1 FROM categories WHERE name = ? AND name != ?", (new, old)).fetchone():
            raise HTTPException(409, "That category exists")
        conn.execute("UPDATE categories SET name = ? WHERE name = ?", (new, old))
        conn.execute("UPDATE receipts SET category = ? WHERE category = ?", (new, old))
        conn.execute("UPDATE rules SET category = ? WHERE category = ?", (new, old))
        _refile(conn, "category = ?", (new,))
    conn.commit()
    return {"ok": True}


@router.delete("/categories/{name}")
def delete_category(name: str, move_to: str = "Other", _: User = Depends(current_user), conn: Conn = Depends(get_db)):
    if name.lower() == move_to.lower():
        raise HTTPException(400, "Pick a different category to move its receipts to")
    if not conn.execute("SELECT 1 FROM categories WHERE name = ?", (move_to,)).fetchone():
        raise HTTPException(400, f"No category {move_to}")
    conn.execute("UPDATE receipts SET category = ? WHERE category = ?", (move_to, name))
    conn.execute("DELETE FROM rules WHERE category = ? AND tag IS NULL", (name,))
    conn.execute("UPDATE rules SET category = NULL WHERE category = ?", (name,))
    conn.execute("DELETE FROM categories WHERE name = ?", (name,))
    _refile(conn, "category = ?", (move_to,))
    conn.commit()
    return {"ok": True}


class Tag(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    color: str = Field(default="#64748b", pattern=COLOR)


@router.get("/tags")
def list_tags(_: User = Depends(current_user), conn: Conn = Depends(get_db)):
    rows = conn.execute(
        "SELECT t.name, t.kind, t.color, (SELECT COUNT(*) FROM receipt_tags rt WHERE rt.tag = t.name) AS count "
        "FROM tags t ORDER BY t.kind = 'plain', t.name COLLATE NOCASE"
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/tags")
def create_tag(body: Tag, _: User = Depends(current_user), conn: Conn = Depends(get_db)):
    try:
        conn.execute("INSERT INTO tags (name, kind, color) VALUES (?, 'plain', ?)", (body.name.strip(), body.color))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "That tag exists")
    conn.commit()
    return body


@router.patch("/tags/{name}")
def update_tag(name: str, body: Tag, _: User = Depends(current_user), conn: Conn = Depends(get_db)):
    row = conn.execute("SELECT name FROM tags WHERE name = ?", (name,)).fetchone()
    if not row:
        raise HTTPException(404, "No such tag")
    old, new = row[0], body.name.strip()
    conn.execute("UPDATE tags SET name = ?, color = ? WHERE name = ?", (new, body.color, old))
    if new != old:
        conn.execute("UPDATE rules SET tag = ? WHERE tag = ?", (new, old))
        _refile(conn, "id IN (SELECT receipt_id FROM receipt_tags WHERE tag = ?)", (new,))
    conn.commit()
    return {"ok": True}


@router.delete("/tags/{name}")
def delete_tag(name: str, _: User = Depends(current_user), conn: Conn = Depends(get_db)):
    row = conn.execute("SELECT kind FROM tags WHERE name = ?", (name,)).fetchone()
    if not row:
        raise HTTPException(404, "No such tag")
    if row[0] != "plain":
        raise HTTPException(400, "Built-in tags with their own fields can't be deleted")
    ids = [r[0] for r in conn.execute("SELECT receipt_id FROM receipt_tags WHERE tag = ?", (name,))]
    conn.execute("DELETE FROM tags WHERE name = ?", (name,))
    conn.execute("UPDATE rules SET tag = NULL WHERE tag = ?", (name,))
    for rid in ids:
        records.reindex_one(conn, rid)
        records.save_sidecar(conn, rid)
    conn.commit()
    return {"ok": True}


class Rule(BaseModel):
    pattern: str = Field(min_length=1, max_length=300)
    field: str = Field(default="merchant", pattern="^(merchant|text)$")
    is_regex: bool = False
    category: str | None = None
    tag: str | None = None
    priority: int = Field(default=150, ge=0, le=1000)


def _check_rule(body: Rule) -> None:
    if not body.category and not body.tag:
        raise HTTPException(422, "A rule needs a category or a tag")
    if body.is_regex:
        try:
            re.compile(body.pattern)
        except re.error as exc:
            raise HTTPException(422, f"Bad pattern: {exc}")


@router.get("/rules")
def list_rules(_: User = Depends(current_user), conn: Conn = Depends(get_db)):
    rows = conn.execute("SELECT * FROM rules ORDER BY source = 'default', priority DESC, id DESC").fetchall()
    return [dict(r) | {"is_regex": bool(r["is_regex"])} for r in rows]


@router.post("/rules")
def create_rule(body: Rule, _: User = Depends(current_user), conn: Conn = Depends(get_db)):
    _check_rule(body)
    cur = conn.execute(
        "INSERT INTO rules (pattern, field, is_regex, category, tag, priority, source, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'user', ?)",
        (body.pattern, body.field, int(body.is_regex), body.category, body.tag, body.priority, now()),
    )
    conn.commit()
    return {"id": cur.lastrowid}


@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, body: Rule, _: User = Depends(current_user), conn: Conn = Depends(get_db)):
    _check_rule(body)
    cur = conn.execute(
        "UPDATE rules SET pattern = ?, field = ?, is_regex = ?, category = ?, tag = ?, priority = ? WHERE id = ?",
        (body.pattern, body.field, int(body.is_regex), body.category, body.tag, body.priority, rule_id),
    )
    if not cur.rowcount:
        raise HTTPException(404, "No such rule")
    conn.commit()
    return {"ok": True}


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, _: User = Depends(current_user), conn: Conn = Depends(get_db)):
    conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
    conn.commit()
    return {"ok": True}


class RuleTest(BaseModel):
    merchant: str = ""
    text: str = ""


@router.post("/rules/test")
def test_rules(body: RuleTest, _: User = Depends(current_user), conn: Conn = Depends(get_db)):
    category, tags, rule_id = categorize.classify(categorize.load_rules(conn), body.merchant, body.text)
    return {"category": category, "tags": tags, "rule_id": rule_id}


@router.get("/merchants")
def list_merchants(_: User = Depends(current_user), conn: Conn = Depends(get_db)):
    rows = conn.execute(
        "SELECT merchant AS name, COUNT(*) AS count, ROUND(SUM(total), 2) AS total, MAX(txn_date) AS last_date "
        "FROM receipts WHERE merchant IS NOT NULL GROUP BY merchant ORDER BY count DESC, merchant"
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/merchant-aliases")
def list_aliases(_: User = Depends(current_user), conn: Conn = Depends(get_db)):
    return [dict(r) for r in conn.execute("SELECT * FROM merchant_aliases ORDER BY canonical, raw_key")]


@router.delete("/merchant-aliases/{raw_key}")
def delete_alias(raw_key: str, _: User = Depends(current_user), conn: Conn = Depends(get_db)):
    conn.execute("DELETE FROM merchant_aliases WHERE raw_key = ?", (raw_key,))
    conn.commit()
    return {"ok": True}
