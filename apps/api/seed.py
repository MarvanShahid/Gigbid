"""Seed the reviewer login (preloaded with a persona) on startup."""
from __future__ import annotations

import os

from sqlalchemy import select

from apps.api.auth.security import hash_password
from apps.api.db import User, put_settings, session

REVIEWER_EMAIL = os.getenv("REVIEWER_EMAIL", "reviewer@gigbid.dev")


def seed_reviewer() -> None:
    pw = os.getenv("REVIEWER_PASSWORD", "reviewer-pass-0800")
    with session() as s:
        if s.scalar(select(User).where(User.email == REVIEWER_EMAIL)):
            return
        s.add(User(id="reviewer", email=REVIEWER_EMAIL, name="Reviewer", password_hash=hash_password(pw)))
        put_settings(s, "reviewer", {"persona": "ml_engineer", "owner": "ml_engineer", "hourly_floor": 35,
                                     "hourly_rate": 45, "onboarded": True})
