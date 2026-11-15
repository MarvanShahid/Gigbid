"""Run orchestration shared by the API (in-process mode) and the Celery worker.

Idempotency (E1): one bid thread per (user, job); the inbox row is unique on
(user, job); a job already analysed is not analysed again unless forced; resumes
are guarded by the approval row's status; submits carry idempotency keys."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import os
import time
import uuid

from langgraph.errors import GraphInterrupt
from langgraph.types import Command
from sqlalchemy import select

from agent import health
from agent.marketplace_port import get_port
from agent.mcp_client import ToolCallError, ToolUnavailable
from agent.memory.promotion_rules import proposal_features, record_outcome
from agent.observability import new_trace_id, set_trace_id
from agent.runtime import graphs, pending_interrupt, thread_config
from apps.api import streaming
from apps.api.db import Approval, JobRow, PipelineCard, Rejection, Run, get_settings, session, user_ctx

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3


def content_hash(job: dict) -> str:
    norm = " ".join((job.get("title", "") + " " + job.get("description", "")).lower().split())
    return hashlib.sha256(norm.encode()).hexdigest()


def _new_run(user_id: str, kind: str, thread_id: str, subject: str) -> tuple[str, str]:
    rid, tid = uuid.uuid4().hex[:16], new_trace_id()
    with session() as s:
        s.add(Run(id=rid, user_id=user_id, kind=kind, thread_id=thread_id, subject=subject, trace_id=tid, events=[]))
    return rid, tid


def _finish_run(rid: str, status: str, state: dict | None = None, error: str | None = None) -> None:
    with session() as s:
        r = s.get(Run, rid)
        r.status, r.finished, r.error = status, time.time(), error
        if state:
            r.tokens, r.cost_usd = int(state.get("tokens", 0) or 0), float(state.get("cost_usd", 0) or 0)


def _ui_evidence(st: dict) -> list[dict]:
    """Evidence shown on the job page: everything the fit matrix points at, then the top-ranked items."""
    ids = {i for m in ((st.get("analyses") or {}).get("fit") or {}).get("matrix", []) for i in m["evidence_ids"]}
    ev = st.get("evidence") or []
    return [e for e in ev if e["id"] in ids] + [e for e in ev if e["id"] not in ids][:8]


def _update_job_from_state(user_id: str, job_id: str, st: dict, status: str) -> None:
    a = st.get("analyses") or {}
    with session() as s:
        row = s.scalar(select(JobRow).where(JobRow.user_id == user_id, JobRow.job_id == job_id))
        if not row:
            return
        row.status, row.updated, row.error = status, time.time(), st.get("error")
        if a.get("fit"):
            row.fit = a["fit"]["score"]
        if a.get("risk"):
            row.risk, row.risk_level = a["risk"]["score"], a["risk"]["level"]
        if st.get("decision"):
            row.recommendation = st["decision"]["action"]
        if st.get("price"):
            row.price, row.connects = st["price"]["amount"], st["price"]["connects_cost"]
        row.summary = {"spec": a.get("spec"), "risk": a.get("risk"), "fit": a.get("fit"), "brief": a.get("brief"),
                       "decision": st.get("decision"), "price": st.get("price"), "evidence": _ui_evidence(st),
                       "verification": {k: v for k, v in (st.get("verification") or {}).items()},
                       "critiques": st.get("critiques"), "compliance": st.get("compliance"),
                       "submission": st.get("submission"), "node_latency": st.get("node_latency"),
                       "tokens": st.get("tokens"), "cost_usd": st.get("cost_usd")}


_THREAD_LOCKS: dict[str, asyncio.Lock] = {}


async def _drive(user_id: str, kind: str, ident: str, inp, rid: str, tid: str) -> dict:
    """Run/resume a graph thread, streaming node updates into the run's event log.
    One run per thread at a time (a second request waits, then sees the finished state)."""
    key = f"{kind}:{user_id}:{ident}"
    lock = _THREAD_LOCKS.setdefault(key, asyncio.Lock())
    async with lock, _sqlite_gate():
        try:
            return await _drive_locked(user_id, kind, ident, inp, rid, tid)
        except GraphInterrupt:
            # the interrupt was raised but surfaced (e.g. a busy checkpointer): the thread is waiting for approval
            async with graphs() as G:
                snap = await G[kind].aget_state(thread_config("bid" if kind == "bid" else "conv", user_id, ident))
            st = dict(snap.values)
            st["_interrupt"], st["_latency_s"] = pending_interrupt(snap), 0.0
            return st


_SQLITE_SEM: asyncio.Semaphore | None = None


def _sqlite_gate():
    """SQLite allows one writer: serialise graph runs in single-process mode. Postgres (compose) runs them in parallel."""
    global _SQLITE_SEM
    if os.getenv("DATABASE_URL", "").startswith("postgres"):
        return contextlib.nullcontext()
    if _SQLITE_SEM is None:
        _SQLITE_SEM = asyncio.Semaphore(1)
    return _SQLITE_SEM


async def _drive_locked(user_id: str, kind: str, ident: str, inp, rid: str, tid: str) -> dict:
    set_trace_id(tid)
    cfg = thread_config("bid" if kind == "bid" else "conv", user_id, ident)
    async with graphs() as G:
        g = G[kind]
        t0 = time.perf_counter()
        if not isinstance(inp, Command):
            snap = await g.aget_state(cfg)
            if snap.next:   # thread already started (e.g. waiting for approval): never start it twice
                st = dict(snap.values)
                st["_interrupt"] = pending_interrupt(snap)
                st["_latency_s"] = 0.0
                if st["_interrupt"] or "approval" in snap.next:
                    return st
                inp = None   # resume an interrupted-by-error thread from its checkpoint
        async for chunk in g.astream(inp, cfg, stream_mode="updates"):
            for node, upd in chunk.items():
                if node == "__interrupt__":
                    streaming.record(rid, "approval" if kind == "bid" else "approve_reply", {}, "node")
                    continue
                streaming.record(rid, node, upd if isinstance(upd, dict) else {})
        snap = await g.aget_state(cfg)
        st = dict(snap.values)
        st["_interrupt"] = pending_interrupt(snap)
        st["_latency_s"] = round(time.perf_counter() - t0, 2)
        return st


def _open_approval(user_id: str, kind: str, thread: str, subject: str, payload: dict) -> None:
    with session() as s:
        existing = s.scalar(select(Approval).where(Approval.user_id == user_id, Approval.thread_id == thread,
                                                   Approval.status == "pending"))
        if existing:
            existing.payload = payload
        else:
            s.add(Approval(id=uuid.uuid4().hex[:16], user_id=user_id, kind=kind, thread_id=thread, subject=subject,
                           payload=payload))


async def run_bid(user_id: str, job_id: str, force: bool = False) -> str:
    rid, tid = _new_run(user_id, "bid", f"bid:{user_id}:{job_id}", job_id)
    with session() as s:
        ctx = user_ctx(s, user_id)
        row = s.scalar(select(JobRow).where(JobRow.user_id == user_id, JobRow.job_id == job_id))
        if row is None:
            row = JobRow(user_id=user_id, job_id=job_id, status="analysing")
            s.add(row)
        row.status, row.attempts = "analysing", row.attempts + 1
        attempts = row.attempts
    inp = {"job_id": job_id, "user": ctx, "trace_id": tid, "force_bid": force}
    try:
        st = await _drive(user_id, "bid", job_id, inp, rid, tid)
    except ToolUnavailable as e:
        _update_job_from_state(user_id, job_id, {}, "queued")
        with session() as s:
            r = s.scalar(select(JobRow).where(JobRow.user_id == user_id, JobRow.job_id == job_id))
            r.error = f"{e.server} unavailable; queued and will retry"
        streaming.record(rid, "degraded", {"detail": str(e)}, "error")
        _finish_run(rid, "queued", error=str(e))
        return rid
    except Exception as e:  # noqa: BLE001
        log.exception("bid run failed")
        status = "dead_letter" if attempts >= MAX_ATTEMPTS else "failed"
        _update_job_from_state(user_id, job_id, {"error": str(e)}, status)
        streaming.record(rid, "error", {"detail": f"{type(e).__name__}: {e}"}, "error")
        _finish_run(rid, status, error=str(e))
        return rid
    status = st.get("status") or "done"
    if st["_interrupt"]:
        status = "awaiting_approval"
        _open_approval(user_id, "proposal", f"bid:{user_id}:{job_id}", job_id, st["_interrupt"])
        _upsert_card(user_id, job_id, st, "drafted")
    _update_job_from_state(user_id, job_id, st, status)
    _finish_run(rid, "waiting" if st["_interrupt"] else "done", st)
    return rid


def _upsert_card(user_id: str, job_id: str, st: dict, stage: str, proposal_id: str | None = None) -> None:
    with session() as s:
        c = s.scalar(select(PipelineCard).where(PipelineCard.user_id == user_id, PipelineCard.job_id == job_id))
        if c is None:
            c = PipelineCard(user_id=user_id, job_id=job_id)
            s.add(c)
        job = st.get("job") or {}
        c.title, c.category = job.get("title", c.title), job.get("category", c.category)
        c.stage, c.updated = stage, time.time()
        if st.get("price"):
            c.bid, c.connects = st["price"]["amount"], st["price"]["connects_cost"]
        if proposal_id:
            c.proposal_id = proposal_id
        if st.get("draft"):
            c.features = proposal_features(st["draft"]["cover_letter"], len(st["draft"].get("citations", [])))
        c.cost_usd = float(st.get("cost_usd") or 0)
        c.latency_s = float(sum((st.get("node_latency") or {}).values()))


async def resume(user_id: str, kind: str, ident: str, value: dict, approval_id: str) -> str:
    rid, tid = _new_run(user_id, "resume", f"{'bid' if kind == 'bid' else 'conv'}:{user_id}:{ident}", ident)
    try:
        st = await _drive(user_id, kind, ident, Command(resume=value), rid, tid)
    except ToolUnavailable as e:
        streaming.record(rid, "degraded", {"detail": str(e)}, "error")
        with session() as s:
            a = s.get(Approval, approval_id)
            a.status = "queued"
        _finish_run(rid, "queued", error=str(e))
        return rid
    except (ToolCallError, Exception) as e:  # noqa: BLE001
        streaming.record(rid, "error", {"detail": f"{type(e).__name__}: {e}"}, "error")
        _finish_run(rid, "failed", error=str(e))
        return rid
    with session() as s:
        a = s.get(Approval, approval_id)
        a.status = {"approve": "approved", "reject": "rejected"}.get(value["action"], "edited")
        a.decided = time.time()
    if st["_interrupt"]:   # an edit goes back through compliance and asks again
        _open_approval(user_id, "proposal" if kind == "bid" else "message",
                       f"{'bid' if kind == 'bid' else 'conv'}:{user_id}:{ident}", ident, st["_interrupt"])
    if kind == "bid":
        if st.get("submission"):
            _upsert_card(user_id, ident, st, "submitted", st["submission"].get("proposal_id"))
            with session() as s:
                a = s.get(Approval, approval_id)
                a.status = "sent"
        elif st.get("status") == "rejected":
            _upsert_card(user_id, ident, st, "lost")
        _update_job_from_state(user_id, ident, st, st.get("status") or "done")
    _finish_run(rid, "waiting" if st["_interrupt"] else "done", st)
    return rid


async def run_conversation(user_id: str, thread_id: str) -> str:
    rid, tid = _new_run(user_id, "conversation", f"conv:{user_id}:{thread_id}", thread_id)
    with session() as s:
        ctx = user_ctx(s, user_id)
    try:
        st = await _drive(user_id, "conversation", thread_id, {"thread_id": thread_id, "user": ctx, "trace_id": tid},
                          rid, tid)
    except ToolUnavailable as e:
        streaming.record(rid, "degraded", {"detail": str(e)}, "error")
        _finish_run(rid, "queued", error=str(e))
        return rid
    if st["_interrupt"]:
        _open_approval(user_id, "message", f"conv:{user_id}:{thread_id}", thread_id, st["_interrupt"])
    _finish_run(rid, "waiting" if st["_interrupt"] else "done", st)
    return rid


async def scout(user_id: str) -> dict:
    """Run saved searches, de-duplicate (same id or same content), queue new jobs."""
    with session() as s:
        st = get_settings(s, user_id)
        seen_ids = {r.job_id for r in s.scalars(select(JobRow).where(JobRow.user_id == user_id))}
        seen_hash = {r.content_hash: r.job_id for r in s.scalars(select(JobRow).where(JobRow.user_id == user_id))}
    port = get_port(user_id)
    new, dups = [], 0
    for search in st.get("saved_searches", []):
        jobs = await port.search_jobs("scout", search.get("query", ""), search.get("category"), 50)
        for j in jobs:
            if j["id"] in seen_ids:
                continue
            if j["budget"]["amount"] < st["filters"].get("min_budget", 0) or \
                    j["category"] in st["filters"].get("exclude_categories", []):
                continue
            h = content_hash(j)
            with session() as s:
                row = JobRow(user_id=user_id, job_id=j["id"], content_hash=h, title=j["title"], category=j["category"],
                             budget=j["budget"]["amount"], connects=j["connects_required"],
                             status="duplicate" if h in seen_hash else "new", duplicate_of=seen_hash.get(h))
                s.add(row)
            seen_ids.add(j["id"])
            if h in seen_hash:
                dups += 1
                continue
            seen_hash[h] = j["id"]
            new.append(j["id"])
    return {"new": new, "duplicates": dups}


async def sync_pipeline(user_id: str) -> dict:
    """Pull proposal statuses and client threads; move cards; feed outcome memory (RULE O)."""
    port = get_port(user_id)
    from agent.mcp_client import gateway
    props = (await gateway().call("system", "list_proposals", {"account": user_id}))["proposals"]
    threads = await port.list_messages("liaison")
    moved, promoted = 0, []
    by_prop = {p["id"]: p for p in props}
    with session() as s:
        cards = list(s.scalars(select(PipelineCard).where(PipelineCard.user_id == user_id)))
    for c in cards:
        p = by_prop.get(c.proposal_id or "")
        if not p:
            continue
        stage = {"submitted": "submitted", "viewed": "viewed", "replied": "replied", "interview": "interview",
                 "hired": "hired"}.get(p["status"], c.stage)
        if stage != c.stage and c.stage != "lost":
            with session() as s:
                cc = s.get(PipelineCard, c.id)
                cc.stage, cc.updated = stage, time.time()
            moved += 1
        outcome = stage if stage in ("replied", "interview", "hired") else "ignored"
        promoted += record_outcome(user_id, c.proposal_id, c.category, c.features or {}, outcome)
    open_threads = []
    with session() as s:
        pending = {a.subject for a in s.scalars(select(Approval).where(Approval.user_id == user_id,
                                                                      Approval.kind == "message",
                                                                      Approval.status == "pending"))}
    for t in threads:
        if t["messages"] and t["messages"][-1]["from"] == "client" and t["id"] not in pending:
            open_threads.append(t["id"])
    return {"moved": moved, "promoted": sorted(set(promoted)), "threads_needing_reply": open_threads}


# --------------------------------------------------------------------------- dispatch
_BG: set[asyncio.Task] = set()
MAIN_LOOP: asyncio.AbstractEventLoop | None = None


def use_celery() -> bool:
    return bool(os.getenv("CELERY_BROKER_URL")) and os.getenv("GIGBID_INLINE_RUNS") != "1"


def dispatch(task: str, **kw) -> None:
    """Long runs go to the Celery worker; without a broker they run as background tasks in this process."""
    if use_celery():
        from worker.tasks import app as celery
        celery.send_task(f"worker.tasks.{task}", kwargs=kw)
        return
    fn = {"run_bid": run_bid, "resume": resume, "run_conversation": run_conversation, "scout": scout,
          "sync_pipeline": sync_pipeline}[task]
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        t = loop.create_task(fn(**kw))
        _BG.add(t)
        t.add_done_callback(_BG.discard)
    elif MAIN_LOOP is not None:          # called from a sync endpoint's worker thread
        asyncio.run_coroutine_threadsafe(fn(**kw), MAIN_LOOP)
    else:
        raise RuntimeError("no event loop to run background work on")


def marketplace_status() -> dict:
    deg = health.degraded()
    return {"degraded": deg, "marketplace_available": "marketplace" not in deg, "detail": health.status()}


def note_rejection(user_id: str, subject: str, reason: str) -> None:
    with session() as s:
        s.add(Rejection(user_id=user_id, subject=subject, reason=reason or "(no reason)"))
