"""Approval grants: the only way a write tool will act for real.

When the user approves in the web UI, the API signs a short-lived JWT that binds
  (account, action, sha256 of the exact payload, approval id).
The marketplace server re-hashes the payload it is asked to send and refuses if
anything differs, if the grant expired, or if the grant was already used. So an
agent cannot send an unapproved or edited-after-approval proposal, even if it
calls the tool directly.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time

import jwt

from agent.settings import data_dir

ALG = "HS256"


def _secret() -> str:
    s = os.getenv("APPROVAL_SECRET")
    if not s:
        s = "dev-approval-secret-change-me-in-production-0800"  # .env.example documents that production must set this
    return s


def payload_hash(action: str, payload: dict) -> str:
    canon = json.dumps({"action": action, **payload}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


def mint(account: str, action: str, payload: dict, approval_id: str, ttl: int = 3600) -> str:
    now = int(time.time())
    return jwt.encode({"sub": account, "act": action, "h": payload_hash(action, payload), "jti": approval_id,
                       "iat": now, "exp": now + ttl}, _secret(), algorithm=ALG)


class GrantError(Exception):
    pass


class GrantLedger:
    """Remembers used grant ids (jti) so a grant authorises exactly one send."""

    def __init__(self, path=None) -> None:
        self.path = str(path or data_dir() / "marketplace_state.db")
        self.lock = threading.Lock()
        with sqlite3.connect(self.path) as c:
            c.execute("CREATE TABLE IF NOT EXISTS used_grants (jti TEXT PRIMARY KEY, used_at REAL)")
            c.execute("CREATE TABLE IF NOT EXISTS idem (account TEXT, key TEXT, result TEXT, PRIMARY KEY(account, key))")
            c.execute("CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, account TEXT, body TEXT, created REAL)")

    def check(self, token: str, account: str, action: str, payload: dict) -> dict:
        try:
            claims = jwt.decode(token, _secret(), algorithms=[ALG])
        except jwt.PyJWTError as e:
            raise GrantError(f"invalid approval grant: {e}") from e
        if claims["sub"] != account or claims["act"] != action:
            raise GrantError("approval grant is for a different account or action")
        if claims["h"] != payload_hash(action, payload):
            raise GrantError("payload differs from what the user approved")
        with self.lock, sqlite3.connect(self.path) as c:
            if c.execute("SELECT 1 FROM used_grants WHERE jti=?", (claims["jti"],)).fetchone():
                raise GrantError("approval grant already used")
        return claims

    def consume(self, jti: str) -> None:
        with self.lock, sqlite3.connect(self.path) as c:
            c.execute("INSERT OR IGNORE INTO used_grants VALUES (?, ?)", (jti, time.time()))

    # idempotency (survives restarts)
    def idem_get(self, account: str, key: str):
        with sqlite3.connect(self.path) as c:
            row = c.execute("SELECT result FROM idem WHERE account=? AND key=?", (account, key)).fetchone()
        return json.loads(row[0]) if row else None

    def idem_put(self, account: str, key: str, result: dict) -> None:
        with self.lock, sqlite3.connect(self.path) as c:
            c.execute("INSERT OR REPLACE INTO idem VALUES (?, ?, ?)", (account, key, json.dumps(result)))

    def save_draft(self, draft_id: str, account: str, body: dict) -> None:
        with self.lock, sqlite3.connect(self.path) as c:
            c.execute("INSERT OR REPLACE INTO drafts VALUES (?, ?, ?, ?)", (draft_id, account, json.dumps(body), time.time()))

    def get_draft(self, draft_id: str, account: str) -> dict | None:
        with sqlite3.connect(self.path) as c:
            row = c.execute("SELECT body FROM drafts WHERE id=? AND account=?", (draft_id, account)).fetchone()
        return json.loads(row[0]) if row else None
