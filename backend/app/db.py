"""SQLite: the index over the receipts folder.

The JSON details file beside each image is the record; every table here can
be rebuilt from them (storage.reindex). WAL mode so the OCR worker can write
while requests read.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from . import config

log = logging.getLogger(__name__)

EMBED_DIM = 384

# Each entry moves user_version up by one. Never edit a shipped entry; add one.
MIGRATIONS = [
    """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY,
        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        display_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('admin', 'member')),
        disabled INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE TABLE sessions (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        user_agent TEXT
    );
    CREATE TABLE receipts (
        seq INTEGER PRIMARY KEY,
        id TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL CHECK (status IN ('queued', 'processing', 'review', 'confirmed', 'failed')),
        merchant TEXT,
        merchant_raw TEXT,
        txn_date TEXT,
        txn_time TEXT,
        subtotal REAL,
        tax REAL,
        total REAL,
        currency TEXT NOT NULL DEFAULT 'USD',
        payment_method TEXT,
        card_last4 TEXT,
        category TEXT,
        notes TEXT,
        file_path TEXT NOT NULL,
        sidecar_path TEXT NOT NULL,
        mime TEXT NOT NULL,
        original_name TEXT,
        raw_text TEXT,
        ocr_confidence REAL,
        parsed_json TEXT,
        suggested_tags TEXT,
        error TEXT,
        embed_hash TEXT,
        created_by TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        confirmed_at TEXT,
        history_json TEXT NOT NULL DEFAULT '[]'
    );
    CREATE INDEX receipts_date ON receipts(txn_date);
    CREATE INDEX receipts_status ON receipts(status);
    CREATE INDEX receipts_category ON receipts(category);
    CREATE INDEX receipts_merchant ON receipts(merchant COLLATE NOCASE);
    CREATE TABLE line_items (
        id INTEGER PRIMARY KEY,
        receipt_id TEXT NOT NULL REFERENCES receipts(id) ON DELETE CASCADE ON UPDATE CASCADE,
        position INTEGER NOT NULL,
        description TEXT NOT NULL,
        qty REAL,
        unit_price REAL,
        amount REAL
    );
    CREATE INDEX line_items_receipt ON line_items(receipt_id);
    CREATE TABLE categories (
        name TEXT PRIMARY KEY COLLATE NOCASE,
        color TEXT NOT NULL,
        sort INTEGER NOT NULL DEFAULT 100
    );
    CREATE TABLE rules (
        id INTEGER PRIMARY KEY,
        pattern TEXT NOT NULL,
        field TEXT NOT NULL CHECK (field IN ('merchant', 'text')),
        is_regex INTEGER NOT NULL DEFAULT 0,
        category TEXT,
        tag TEXT,
        priority INTEGER NOT NULL DEFAULT 100,
        source TEXT NOT NULL CHECK (source IN ('default', 'user')),
        created_at TEXT NOT NULL
    );
    CREATE TABLE tags (
        name TEXT PRIMARY KEY COLLATE NOCASE,
        kind TEXT NOT NULL CHECK (kind IN ('plain', 'hsa', 'donation', 'warranty')),
        color TEXT NOT NULL
    );
    CREATE TABLE receipt_tags (
        receipt_id TEXT NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
        tag TEXT NOT NULL REFERENCES tags(name) ON DELETE CASCADE ON UPDATE CASCADE,
        PRIMARY KEY (receipt_id, tag)
    );
    CREATE TABLE hsa (
        receipt_id TEXT PRIMARY KEY REFERENCES receipts(id) ON DELETE CASCADE,
        patient TEXT,
        provider TEXT,
        eligible_amount REAL,
        reimbursed INTEGER NOT NULL DEFAULT 0,
        reimbursed_date TEXT,
        claim_ref TEXT
    );
    CREATE TABLE donation (
        receipt_id TEXT PRIMARY KEY REFERENCES receipts(id) ON DELETE CASCADE,
        organization TEXT,
        ein TEXT,
        donation_type TEXT CHECK (donation_type IN ('cash', 'noncash')),
        deductible_amount REAL,
        items_description TEXT,
        acknowledgment INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE warranty (
        receipt_id TEXT PRIMARY KEY REFERENCES receipts(id) ON DELETE CASCADE,
        product TEXT,
        serial TEXT,
        expires_on TEXT
    );
    CREATE TABLE attachments (
        id TEXT PRIMARY KEY,
        receipt_id TEXT NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
        file_path TEXT NOT NULL,
        mime TEXT NOT NULL,
        original_name TEXT,
        label TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE merchant_aliases (
        raw_key TEXT PRIMARY KEY,
        canonical TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE VIRTUAL TABLE receipts_fts USING fts5(merchant, body, tokenize = 'porter unicode61');
    CREATE VIRTUAL TABLE receipts_tri USING fts5(merchant, body, tokenize = 'trigram');
    """,
]


class Conn(sqlite3.Connection):
    vec_enabled: bool = False


def _load_vec(conn: Conn) -> bool:
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception as exc:  # noqa: BLE001 - any failure just turns vectors off
        log.warning("sqlite-vec unavailable, semantic search off: %s", exc)
        return False


def connect() -> Conn:
    path = config.settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, factory=Conn, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.vec_enabled = _load_vec(conn)
    return conn


def migrate(conn: Conn) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
        log.info("migrating database to version %d", i)
        conn.executescript(f"BEGIN; {script}; PRAGMA user_version = {i}; COMMIT;")
    if conn.vec_enabled:
        # Outside the migrations: a box without the extension still migrates.
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS receipts_vec USING vec0(embedding float[{EMBED_DIM}] distance_metric=cosine)"
        )
        conn.commit()


@contextmanager
def session() -> Iterator[Conn]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def get_db() -> Iterator[Conn]:
    """FastAPI dependency: one connection per request."""
    with session() as conn:
        yield conn
