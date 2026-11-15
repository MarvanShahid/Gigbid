"""Job inbox, job detail, scouting and analysis triggers."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from agent.marketplace_port import get_port
from agent.mcp_client import ToolCallError, ToolUnavailable
from apps.api import services
from apps.api.auth.security import CurrentUser
from apps.api.db import Approval, JobRow, Run, session
from apps.api.schemas.models import Accepted, JobCard, JobDetail

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

ORDER = {"awaiting_approval": 0, "drafting": 1, "analysing": 2, "new": 3, "queued": 3, "watch": 4, "submitted": 5,
         "skipped": 6, "rejected": 7, "blocked": 7, "needs_attention": 1, "dead_letter": 8, "duplicate": 9}


def card(r: JobRow) -> JobCard:
    return JobCard(job_id=r.job_id, title=r.title, category=r.category, status=r.status, fit=r.fit, risk=r.risk,
                   risk_level=r.risk_level, recommendation=r.recommendation, price=r.price, connects=r.connects,
                   budget=r.budget, error=r.error, duplicate_of=r.duplicate_of, updated=r.updated)


@router.get("", response_model=list[JobCard])
def inbox(status: str | None = None, recommendation: str | None = None, q: str | None = None,
          include_skipped: bool = True, user: str = CurrentUser) -> list[JobCard]:
    with session() as s:
        rows = list(s.scalars(select(JobRow).where(JobRow.user_id == user)))
    if status:
        rows = [r for r in rows if r.status == status]
    if recommendation:
        rows = [r for r in rows if r.recommendation == recommendation]
    if q:
        rows = [r for r in rows if q.lower() in (r.title or "").lower()]
    if not include_skipped:
        rows = [r for r in rows if r.status not in ("skipped", "duplicate")]
    rows.sort(key=lambda r: (ORDER.get(r.status, 5), -(r.fit or -1), -r.updated))
    return [card(r) for r in rows]


@router.post("/scout", response_model=Accepted)
async def scout_now(user: str = CurrentUser) -> Accepted:
    try:
        res = await services.scout(user)
    except ToolUnavailable as e:
        raise HTTPException(503, f"marketplace unavailable: {e}") from e
    for jid in res["new"]:
        services.dispatch("run_bid", user_id=user, job_id=jid)
    return Accepted(detail=f"{len(res['new'])} new jobs queued, {res['duplicates']} duplicates ignored")


@router.get("/{job_id}", response_model=JobDetail)
async def detail(job_id: str, user: str = CurrentUser) -> JobDetail:
    with session() as s:
        r = s.scalar(select(JobRow).where(JobRow.user_id == user, JobRow.job_id == job_id))
        if not r:
            raise HTTPException(404, "job not in your inbox")
        ap = s.scalar(select(Approval).where(Approval.user_id == user, Approval.subject == job_id,
                                             Approval.kind == "proposal", Approval.status == "pending"))
        runs = [{"id": x.id, "kind": x.kind, "status": x.status, "started": x.started, "trace_id": x.trace_id}
                for x in s.scalars(select(Run).where(Run.user_id == user, Run.subject == job_id))]
    try:
        job = await get_port(user).get_job("scout", job_id)
    except (ToolUnavailable, ToolCallError):
        job = None
    c = card(r)
    return JobDetail(**c.model_dump(), job=job, summary=r.summary or {}, approval_id=ap.id if ap else None,
                     runs=sorted(runs, key=lambda x: -x["started"]))


@router.post("/{job_id}/analyse", response_model=Accepted)
def analyse(job_id: str, force_bid: bool = False, user: str = CurrentUser) -> Accepted:
    with session() as s:
        r = s.scalar(select(JobRow).where(JobRow.user_id == user, JobRow.job_id == job_id))
        if r is None:
            s.add(JobRow(user_id=user, job_id=job_id, status="new"))
        elif r.status in ("analysing", "drafting", "awaiting_approval", "submitted") and not force_bid:
            return Accepted(detail="already running")
        elif r.status == "awaiting_approval":
            return Accepted(detail="already waiting for your approval")
    services.dispatch("run_bid", user_id=user, job_id=job_id, force=force_bid)
    return Accepted(detail="queued")


@router.post("/{job_id}/skip", response_model=Accepted)
def skip(job_id: str, user: str = CurrentUser) -> Accepted:
    with session() as s:
        r = s.scalar(select(JobRow).where(JobRow.user_id == user, JobRow.job_id == job_id))
        if not r:
            raise HTTPException(404, "job not found")
        r.status = "skipped"
    return Accepted(detail="skipped")
