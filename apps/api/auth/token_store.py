"""Encrypted per-user secret store (OAuth tokens, marketplace credentials).
Fernet (AES-128-CBC + HMAC) with TOKEN_ENC_KEY from the environment; values are
never logged (agent.observability masks token-like strings everywhere)."""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet

from apps.api.db import Secret, session


def _fernet() -> Fernet:
    key = os.getenv("TOKEN_ENC_KEY")
    if not key:
        # dev only: derive a stable key from the session secret so restarts can still decrypt
        seed = os.getenv("SESSION_SECRET", "dev-session-secret-change-me-in-production-0800")
        key = base64.urlsafe_b64encode(hashlib.sha256(seed.encode()).digest()).decode()
    return Fernet(key.encode())


class TokenStore:
    def put(self, user_id: str, name: str, value: str) -> None:
        ct = _fernet().encrypt(value.encode()).decode()
        with session() as s:
            row = s.get(Secret, (user_id, name))
            if row:
                row.ciphertext = ct
            else:
                s.add(Secret(user_id=user_id, name=name, ciphertext=ct))

    def get(self, user_id: str, name: str) -> str | None:
        with session() as s:
            row = s.get(Secret, (user_id, name))
            return _fernet().decrypt(row.ciphertext.encode()).decode() if row else None

    def delete(self, user_id: str, name: str) -> None:
        with session() as s:
            row = s.get(Secret, (user_id, name))
            if row:
                s.delete(row)

    def names(self, user_id: str) -> list[str]:
        from sqlalchemy import select
        with session() as s:
            return [r.name for r in s.scalars(select(Secret).where(Secret.user_id == user_id))]
