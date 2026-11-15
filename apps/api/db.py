"""Application database (users, settings, inbox, runs, approvals, pipeline, secrets).
Postgres in docker compose (DATABASE_URL), SQLite file otherwise. Every query is
scoped by user_id (tenant)."""
from __future__ import annotations

import os
import time
from contextlib import contextmanager

from sqlalchemy import JSON, Float, Integer, String, Text, UniqueConstraint, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from agent.settings import data_dir


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(200))
    created: Mapped[float] = mapped_column(Float, default=time.time)


class Settings(Base):
    __tablename__ = "settings"
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class JobRow(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("user_id", "job_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    job_id: Mapped[str] = mapped_column(String(80))
    content_hash: Mapped[str] = mapped_column(String(64), index=True, default="")
    title: Mapped[str] = mapped_column(String(300), default="")
    category: Mapped[str] = mapped_column(String(60), default="")
    status: Mapped[str] = mapped_column(String(40), default="new")
    fit: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(10), nullable=True)
    recommendation: Mapped[str | None] = mapped_column(String(10), nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    connects: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    duplicate_of: Mapped[str | None] = mapped_column(String(80), nullable=True)
    updated: Mapped[float] = mapped_column(Float, default=time.time)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(20))          # bid | conversation | resume | scout
    thread_id: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(120))      # job id or message thread id
    status: Mapped[str] = mapped_column(String(30), default="running")
    trace_id: Mapped[str] = mapped_column(String(64))
    started: Mapped[float] = mapped_column(Float, default=time.time)
    finished: Mapped[float | None] = mapped_column(Float, nullable=True)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    events: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(20))          # proposal | message
    thread_id: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="pending")   # pending | approved | edited | rejected | sent
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    decision: Mapped[dict] = mapped_column(JSON, default=dict)
    created: Mapped[float] = mapped_column(Float, default=time.time)
    decided: Mapped[float | None] = mapped_column(Float, nullable=True)


class PipelineCard(Base):
    __tablename__ = "pipeline"
    __table_args__ = (UniqueConstraint("user_id", "job_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    job_id: Mapped[str] = mapped_column(String(80))
    proposal_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    category: Mapped[str] = mapped_column(String(60), default="")
    stage: Mapped[str] = mapped_column(String(20), default="drafted")
    bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    connects: Mapped[int] = mapped_column(Integer, default=0)
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_s: Mapped[float] = mapped_column(Float, default=0.0)
    updated: Mapped[float] = mapped_column(Float, default=time.time)


class Secret(Base):
    __tablename__ = "secrets"
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)


class Rejection(Base):
    __tablename__ = "rejections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    subject: Mapped[str] = mapped_column(String(120))
    reason: Mapped[str] = mapped_column(Text)
    at: Mapped[float] = mapped_column(Float, default=time.time)


_engine = None
_Session = None


def engine():
    global _engine, _Session
    if _engine is None:
        url = os.getenv("DATABASE_URL") or f"sqlite:///{data_dir() / 'gigbid.db'}"
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        _engine = create_engine(url, pool_pre_ping=True,
                                connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
        Base.metadata.create_all(_engine)
        _Session = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def reset_engine() -> None:
    global _engine, _Session
    _engine = _Session = None


@contextmanager
def session() -> Session:
    engine()
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


DEFAULT_SETTINGS = {
    "owner": "ml_engineer", "persona": "ml_engineer", "hourly_floor": 35, "hourly_rate": 45,
    "weekly_connects_budget": 120, "autonomy": "suggest", "marketplace": "gigsim",
    "saved_searches": [{"name": "All my categories", "query": "", "category": None, "every_hours": 4}],
    "filters": {"min_budget": 300, "exclude_categories": []}, "onboarded": False,
}


def get_settings(s: Session, user_id: str) -> dict:
    row = s.get(Settings, user_id)
    return {**DEFAULT_SETTINGS, **(row.data if row else {})}


def put_settings(s: Session, user_id: str, data: dict) -> dict:
    row = s.get(Settings, user_id)
    merged = {**DEFAULT_SETTINGS, **(row.data if row else {}), **data}
    if row:
        row.data = merged
    else:
        s.add(Settings(user_id=user_id, data=merged))
    return merged


def user_ctx(s: Session, user_id: str) -> dict:
    st = get_settings(s, user_id)
    week_ago = time.time() - 7 * 86400
    spent = sum(c.connects for c in s.scalars(select(PipelineCard).where(
        PipelineCard.user_id == user_id, PipelineCard.updated >= week_ago, PipelineCard.stage != "drafted")))
    return {"account": user_id, "owner": st["owner"], "hourly_floor": float(st["hourly_floor"]),
            "hourly_rate": float(st["hourly_rate"]), "autonomy": st["autonomy"],
            "weekly_connects_budget": int(st["weekly_connects_budget"]), "connects_spent_week": spent}
