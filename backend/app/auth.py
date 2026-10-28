"""Household accounts: argon2id passwords, cookie sessions, a login throttle."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request

from . import config
from .db import Conn, get_db

COOKIE = "rcpt_session"
_hasher = PasswordHasher()


@dataclass
class User:
    id: int
    username: str
    display_name: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def to_dict(self) -> dict:
        return {"id": self.id, "username": self.username, "display_name": self.display_name, "role": self.role}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored: str, password: str) -> bool:
    try:
        return _hasher.verify(stored, password)
    except (VerificationError, InvalidHashError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(conn: sqlite3.Connection, user_id: int, user_agent: str | None) -> str:
    token = secrets.token_urlsafe(32)
    now = _now()
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, created_at, expires_at, user_agent) VALUES (?, ?, ?, ?, ?)",
        (_token_hash(token), user_id, now.isoformat(), (now + timedelta(days=config.settings.session_days)).isoformat(),
         (user_agent or "")[:200]),
    )
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now.isoformat(),))
    conn.commit()
    return token


def end_session(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
    conn.commit()


def user_for_token(conn: sqlite3.Connection, token: str | None) -> User | None:
    if not token:
        return None
    row = conn.execute(
        "SELECT u.id, u.username, u.display_name, u.role, s.expires_at, s.created_at FROM sessions s "
        "JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND u.disabled = 0",
        (_token_hash(token),),
    ).fetchone()
    if not row:
        return None
    now = _now()
    expires = datetime.fromisoformat(row["expires_at"])
    if expires < now:
        return None
    # Sliding expiry, refreshed at most daily so reads don't all write.
    full = timedelta(days=config.settings.session_days)
    if expires - now < full - timedelta(days=1):
        conn.execute(
            "UPDATE sessions SET expires_at = ? WHERE token_hash = ?", ((now + full).isoformat(), _token_hash(token))
        )
        conn.commit()
    return User(row["id"], row["username"], row["display_name"], row["role"])


def user_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def create_user(conn: sqlite3.Connection, username: str, display_name: str, password: str, role: str) -> User:
    cur = conn.execute(
        "INSERT INTO users (username, display_name, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
        (username, display_name or username, hash_password(password), role, _now().isoformat()),
    )
    conn.commit()
    return User(cur.lastrowid, username, display_name or username, role)


def authenticate(conn: sqlite3.Connection, username: str, password: str) -> User | None:
    row = conn.execute(
        "SELECT id, username, display_name, role, password_hash FROM users WHERE username = ? AND disabled = 0",
        (username,),
    ).fetchone()
    if not row:
        # Same work as a real check, so timing doesn't tell which usernames exist.
        verify_password(_DUMMY_HASH, password)
        return None
    if not verify_password(row["password_hash"], password):
        return None
    if _hasher.check_needs_rehash(row["password_hash"]):
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), row["id"]))
        conn.commit()
    return User(row["id"], row["username"], row["display_name"], row["role"])


_DUMMY_HASH = _hasher.hash(secrets.token_hex(8))


class LoginThrottle:
    """At most `limit` failed logins per client IP per `window` seconds."""

    def __init__(self, limit: int = 10, window: float = 900):
        self.limit, self.window = limit, window
        self._fails: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, q: deque, now: float) -> None:
        while q and now - q[0] > self.window:
            q.popleft()

    def blocked(self, key: str) -> bool:
        with self._lock:
            q = self._fails[key]
            self._trim(q, time.monotonic())
            return len(q) >= self.limit

    def fail(self, key: str) -> None:
        with self._lock:
            self._fails[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


throttle = LoginThrottle()


def client_ip(request: Request) -> str:
    # Caddy sets X-Forwarded-For; the app only listens on 127.0.0.1 behind it.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def optional_user(request: Request, conn: Conn = Depends(get_db)) -> User | None:
    return user_for_token(conn, request.cookies.get(COOKIE))


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in first")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admins only")
    return user
