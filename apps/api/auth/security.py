"""Users, password hashing and session tokens."""
from __future__ import annotations

import os
import re
import time
import uuid

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from apps.api.db import User, session

ALG = "HS256"


def _secret() -> str:
    return os.getenv("SESSION_SECRET", "dev-session-secret-change-me-in-production-0800")


def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def verify_password(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode(), h.encode())
    except ValueError:
        return False


def user_id_for(email: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", email.split("@")[0].lower()).strip("-")[:24] or "user"
    return f"{base}-{uuid.uuid4().hex[:6]}"


def create_user(email: str, password: str, name: str = "", user_id: str | None = None) -> User:
    with session() as s:
        if s.scalar(select(User).where(User.email == email.lower())):
            raise HTTPException(409, "email already registered")
        u = User(id=user_id or user_id_for(email), email=email.lower(), name=name, password_hash=hash_password(password))
        s.add(u)
        return u


def issue_token(user_id: str, ttl: int = 7 * 86400) -> str:
    now = int(time.time())
    return jwt.encode({"sub": user_id, "iat": now, "exp": now + ttl}, _secret(), algorithm=ALG)


def current_user(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    tok = auth[7:] if auth.startswith("Bearer ") else request.cookies.get("gigbid_session") or request.query_params.get("token")
    if not tok:
        raise HTTPException(401, "not signed in")
    try:
        return jwt.decode(tok, _secret(), algorithms=[ALG])["sub"]
    except jwt.PyJWTError as e:
        raise HTTPException(401, "session expired") from e


CurrentUser = Depends(current_user)
