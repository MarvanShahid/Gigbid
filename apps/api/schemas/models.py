"""Request and response models (the TypeScript client is generated from these via OpenAPI)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field("", max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    token: str
    user_id: str
    name: str


class Me(BaseModel):
    user_id: str
    email: str
    name: str
    settings: dict[str, Any]


class SavedSearch(BaseModel):
    name: str = Field(max_length=80)
    query: str = Field("", max_length=200)
    category: str | None = None
    every_hours: int = Field(4, ge=1, le=48)


class SettingsIn(BaseModel):
    persona: str | None = None
    owner: str | None = None
    hourly_floor: float | None = Field(None, ge=1, le=1000)
    hourly_rate: float | None = Field(None, ge=1, le=1000)
    weekly_connects_budget: int | None = Field(None, ge=0, le=2000)
    autonomy: Literal["suggest", "auto_skip"] | None = None
    marketplace: Literal["gigsim", "upwork_live"] | None = None
    saved_searches: list[SavedSearch] | None = None
    filters: dict[str, Any] | None = None
    onboarded: bool | None = None


class JobCard(BaseModel):
    job_id: str
    title: str
    category: str
    status: str
    fit: float | None
    risk: float | None
    risk_level: str | None
    recommendation: str | None
    price: float | None
    connects: int | None
    budget: float | None
    error: str | None = None
    duplicate_of: str | None = None
    updated: float


class JobDetail(JobCard):
    job: dict[str, Any] | None = None
    summary: dict[str, Any]
    approval_id: str | None = None
    runs: list[dict[str, Any]] = []


class ApprovalOut(BaseModel):
    id: str
    kind: str
    subject: str
    status: str
    payload: dict[str, Any]
    created: float


class DecisionIn(BaseModel):
    action: Literal["approve", "edit", "reject", "regenerate"]
    text: str | None = Field(None, max_length=5000)
    answers: list[str] | None = None
    reason: str | None = Field(None, max_length=500)
    slot: dict[str, Any] | None = None
    paragraph: int | None = Field(None, ge=0, le=20, description="for regenerate: sentence index in the cover letter")


class RunOut(BaseModel):
    id: str
    kind: str
    subject: str
    status: str
    trace_id: str
    started: float
    finished: float | None
    tokens: int
    cost_usd: float
    events: list[dict[str, Any]]
    error: str | None
    trace_url: str | None = None


class Accepted(BaseModel):
    ok: bool = True
    run_id: str | None = None
    detail: str = ""


class StatusOut(BaseModel):
    marketplace_available: bool
    degraded: list[str]
    detail: dict[str, Any]
    policy: dict[str, Any] | None = None


class PipelineOut(BaseModel):
    stages: list[str]
    cards: list[dict[str, Any]]


class StageIn(BaseModel):
    stage: Literal["drafted", "submitted", "viewed", "replied", "interview", "hired", "lost"]
