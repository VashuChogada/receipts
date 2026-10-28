from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .. import auth, config
from ..auth import User, admin_user, current_user, optional_user
from ..db import Conn, get_db

router = APIRouter(prefix="/api", tags=["auth"])

USERNAME = r"^[A-Za-z0-9._-]{2,32}$"


class Setup(BaseModel):
    username: str = Field(pattern=USERNAME)
    display_name: str = Field(default="", max_length=60)
    password: str = Field(min_length=8, max_length=200)


class Login(BaseModel):
    username: str
    password: str


class NewUser(Setup):
    role: str = Field(default="member", pattern="^(admin|member)$")


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=60)
    role: str | None = Field(default=None, pattern="^(admin|member)$")
    disabled: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=200)


class PasswordChange(BaseModel):
    current: str
    new: str = Field(min_length=8, max_length=200)


def _set_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        auth.COOKIE, token,
        max_age=config.settings.session_days * 86400,
        httponly=True, samesite="lax",
        secure=request.headers.get("x-forwarded-proto", request.url.scheme) == "https",
        path="/",
    )


@router.get("/auth/state")
def state(user: User | None = Depends(optional_user), conn: Conn = Depends(get_db)):
    return {
        "needs_setup": auth.user_count(conn) == 0,
        "user": user.to_dict() if user else None,
        "server": {"currency": config.settings.currency},
    }


@router.post("/auth/setup")
def setup(body: Setup, request: Request, response: Response, conn: Conn = Depends(get_db)):
    if auth.user_count(conn) > 0:
        raise HTTPException(409, "Already set up; sign in instead")
    user = auth.create_user(conn, body.username, body.display_name, body.password, "admin")
    _set_cookie(request, response, auth.create_session(conn, user.id, request.headers.get("user-agent")))
    return {"user": user.to_dict()}


@router.post("/auth/login")
def login(body: Login, request: Request, response: Response, conn: Conn = Depends(get_db)):
    ip = auth.client_ip(request)
    if auth.throttle.blocked(ip):
        raise HTTPException(429, "Too many tries; wait 15 minutes")
    user = auth.authenticate(conn, body.username.strip(), body.password)
    if not user:
        auth.throttle.fail(ip)
        raise HTTPException(401, "Wrong username or password")
    auth.throttle.reset(ip)
    _set_cookie(request, response, auth.create_session(conn, user.id, request.headers.get("user-agent")))
    return {"user": user.to_dict()}


@router.post("/auth/logout")
def logout(request: Request, response: Response, conn: Conn = Depends(get_db)):
    token = request.cookies.get(auth.COOKIE)
    if token:
        auth.end_session(conn, token)
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


@router.post("/auth/password")
def change_password(body: PasswordChange, user: User = Depends(current_user), conn: Conn = Depends(get_db)):
    if not auth.authenticate(conn, user.username, body.current):
        raise HTTPException(400, "Current password is wrong")
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (auth.hash_password(body.new), user.id))
    conn.commit()
    return {"ok": True}


@router.get("/users")
def list_users(user: User = Depends(current_user), conn: Conn = Depends(get_db)):
    rows = conn.execute(
        "SELECT id, username, display_name, role, disabled, created_at FROM users ORDER BY username COLLATE NOCASE"
    ).fetchall()
    out = [dict(r) for r in rows]
    if not user.is_admin:
        out = [{k: r[k] for k in ("id", "username", "display_name")} for r in out if not r["disabled"]]
    return out


@router.post("/users")
def create_user(body: NewUser, _: User = Depends(admin_user), conn: Conn = Depends(get_db)):
    try:
        user = auth.create_user(conn, body.username, body.display_name, body.password, body.role)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "That username is taken")
    return user.to_dict()


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserPatch, admin: User = Depends(admin_user), conn: Conn = Depends(get_db)):
    if not conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
        raise HTTPException(404, "No such user")
    if user_id == admin.id and (body.role == "member" or body.disabled):
        raise HTTPException(400, "You can't demote or disable yourself")
    if body.display_name is not None:
        conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (body.display_name, user_id))
    if body.role is not None:
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (body.role, user_id))
    if body.disabled is not None:
        conn.execute("UPDATE users SET disabled = ? WHERE id = ?", (int(body.disabled), user_id))
        if body.disabled:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    if body.password:
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (auth.hash_password(body.password), user_id))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    conn.commit()
    return {"ok": True}
