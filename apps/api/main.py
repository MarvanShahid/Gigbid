"""GigBid API (FastAPI).

    uvicorn apps.api.main:app --port 8000

Every request gets a trace id (x-trace-id in, x-trace-id out) that flows through the
graph, MCP servers and the audit log."""
from __future__ import annotations

import asyncio
import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from agent.mcp_client import ToolUnavailable
from agent.observability import new_trace_id, set_trace_id, span
from apps.api.db import engine
from apps.api.routers import analytics, approvals, auth, jobs, messages, pipeline, runs, settings
from apps.api.seed import seed_reviewer

log = logging.getLogger("gigbid.api")
app = FastAPI(title="GigBid API", version="0.1.0",
              description="Multi-agent freelancer copilot. Every proposal and message needs human approval.")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

for r in (auth, jobs, approvals, runs, messages, pipeline, analytics, settings):
    app.include_router(r.router)


@app.middleware("http")
async def trace_mw(request: Request, call_next):
    tid = request.headers.get("x-trace-id") or new_trace_id()
    set_trace_id(tid)
    with span("api.request", method=request.method, path=request.url.path):
        resp = await call_next(request)
    resp.headers["x-trace-id"] = tid
    return resp


@app.exception_handler(ToolUnavailable)
async def unavailable(_: Request, exc: ToolUnavailable):
    return JSONResponse({"detail": f"{exc.server} unavailable", "degraded": True}, status_code=503)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


async def _requeue_loop() -> None:
    """Without Celery (single-process mode), retry jobs queued while the marketplace was down."""
    from sqlalchemy import select

    from agent import health as h
    from apps.api import services
    from apps.api.db import JobRow, session
    while True:
        await asyncio.sleep(30)
        if "marketplace" in h.degraded() or services.use_celery():
            continue
        with session() as s:
            q = [(r.user_id, r.job_id) for r in s.scalars(select(JobRow).where(JobRow.status == "queued"))]
        for u, j in q[:10]:
            services.dispatch("run_bid", user_id=u, job_id=j)


@app.on_event("startup")
async def startup() -> None:
    from apps.api import services
    services.MAIN_LOOP = asyncio.get_running_loop()
    engine()
    seed_reviewer()
    if os.getenv("GIGBID_INLINE_RUNS") == "1" or not os.getenv("CELERY_BROKER_URL"):
        asyncio.get_event_loop().create_task(_requeue_loop())
