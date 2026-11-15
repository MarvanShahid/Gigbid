"""Agent run viewer: list runs, stream node-by-node progress (SSE), open the trace."""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from agent.observability import read_trace
from apps.api.auth.security import CurrentUser
from apps.api.db import Run, session
from apps.api.schemas.models import RunOut
from apps.api.streaming import sse

router = APIRouter(prefix="/api/runs", tags=["runs"])


def trace_url(trace_id: str) -> str:
    base = os.getenv("PHOENIX_UI_URL")
    return f"{base.rstrip('/')}/projects?traceId={trace_id}" if base else f"/api/runs/traces/{trace_id}"


def out(r: Run) -> RunOut:
    return RunOut(id=r.id, kind=r.kind, subject=r.subject, status=r.status, trace_id=r.trace_id, started=r.started,
                  finished=r.finished, tokens=r.tokens, cost_usd=r.cost_usd, events=r.events or [], error=r.error,
                  trace_url=trace_url(r.trace_id))


@router.get("", response_model=list[RunOut])
def list_runs(subject: str | None = None, limit: int = 50, user: str = CurrentUser) -> list[RunOut]:
    with session() as s:
        q = select(Run).where(Run.user_id == user)
        if subject:
            q = q.where(Run.subject == subject)
        rows = list(s.scalars(q.order_by(Run.started.desc()).limit(min(limit, 200))))
    return [out(r) for r in rows]


@router.get("/traces/{trace_id}")
def trace(trace_id: str, user: str = CurrentUser) -> dict:
    with session() as s:
        if not s.scalar(select(Run).where(Run.user_id == user, Run.trace_id == trace_id)):
            raise HTTPException(404, "trace not found")
    spans = read_trace(trace_id)
    by_node: dict[str, dict] = {}
    for sp in spans:
        a = sp["attributes"]
        n = a.get("node") or sp["name"]
        d = by_node.setdefault(n, {"tokens": 0, "cost_usd": 0.0, "ms": 0.0})
        d["tokens"] += int(a.get("tokens_in", 0) or 0) + int(a.get("tokens_out", 0) or 0)
        d["cost_usd"] += float(a.get("cost_usd", 0) or 0)
        if sp["name"].startswith("node."):
            d["ms"] += sp["duration_ms"]
    return {"trace_id": trace_id, "spans": spans, "per_node": by_node}


@router.get("/{run_id}", response_model=RunOut)
def get_run(run_id: str, user: str = CurrentUser) -> RunOut:
    with session() as s:
        r = s.get(Run, run_id)
        if not r or r.user_id != user:
            raise HTTPException(404, "run not found")
        return out(r)


@router.get("/{run_id}/stream")
async def stream(run_id: str, user: str = CurrentUser):
    return await sse(run_id, user)
