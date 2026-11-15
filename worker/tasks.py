"""Background worker (Celery on Redis): scheduled scouting, long agent runs, resumes, pipeline sync.

    celery -A worker.tasks worker -B --loglevel=info

Idempotency: jobs are keyed by (user, job id) and de-duplicated by content hash, so a worker
restart never double-analyses; submits and messages carry idempotency keys, so a retried
resume never double-sends. Live mode (Upwork) polls at most every `marketplace.live_poll_minutes`.
"""
from __future__ import annotations

import asyncio
import os
import time

from celery import Celery
from sqlalchemy import select

from agent.settings import config

BROKER = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
app = Celery("gigbid", broker=BROKER, backend=os.getenv("CELERY_RESULT_BACKEND", BROKER))
app.conf.update(task_acks_late=True, task_reject_on_worker_lost=True, worker_prefetch_multiplier=1,
                task_default_retry_delay=60, timezone="Asia/Karachi")

# check every 15 minutes which saved searches are due (each search has its own every_hours)
app.conf.beat_schedule = {
    "scout-due-searches": {"task": "worker.tasks.scout_due", "schedule": 15 * 60},
    "sync-pipelines": {"task": "worker.tasks.sync_all", "schedule": 30 * 60},
    "retry-queued": {"task": "worker.tasks.retry_queued", "schedule": 5 * 60},
}


def _run(coro):
    return asyncio.run(coro)


@app.task(name="worker.tasks.run_bid", bind=True, max_retries=3)
def run_bid(self, user_id: str, job_id: str, force: bool = False):
    from apps.api import services
    return _run(services.run_bid(user_id, job_id, force))


@app.task(name="worker.tasks.resume", bind=True, max_retries=5)
def resume(self, user_id: str, kind: str, ident: str, value: dict, approval_id: str):
    from apps.api import services
    rid = _run(services.resume(user_id, kind, ident, value, approval_id))
    from apps.api.db import Run, session
    with session() as s:
        if s.get(Run, rid).status == "queued":      # marketplace down: retry the same resume later
            raise self.retry(countdown=60)
    return rid


@app.task(name="worker.tasks.run_conversation")
def run_conversation(user_id: str, thread_id: str):
    from apps.api import services
    return _run(services.run_conversation(user_id, thread_id))


@app.task(name="worker.tasks.scout")
def scout(user_id: str):
    from apps.api import services
    res = _run(services.scout(user_id))
    for jid in res["new"]:
        run_bid.delay(user_id, jid)
    return res


@app.task(name="worker.tasks.sync_pipeline")
def sync_pipeline(user_id: str):
    from apps.api import services
    res = _run(services.sync_pipeline(user_id))
    for tid in res["threads_needing_reply"]:
        run_conversation.delay(user_id, tid)
    return res


@app.task(name="worker.tasks.scout_due")
def scout_due():
    """Run each user's saved searches whose interval has elapsed. Live mode never polls faster than
    marketplace.live_poll_minutes."""
    from apps.api.db import Settings, session
    now = time.time()
    live_min = config()["marketplace"]["live_poll_minutes"] * 60
    due = []
    with session() as s:
        for row in s.scalars(select(Settings)):
            data = dict(row.data or {})
            last = data.get("_last_scout", 0)
            every = min((x.get("every_hours", 4) for x in data.get("saved_searches", [])), default=4) * 3600
            if data.get("marketplace") == "upwork_live":
                every = max(every, live_min)
            if now - last >= every:
                data["_last_scout"] = now
                row.data = data
                due.append(row.user_id)
    for u in due:
        scout.delay(u)
    return due


@app.task(name="worker.tasks.sync_all")
def sync_all():
    from apps.api.db import PipelineCard, session
    with session() as s:
        users = {c.user_id for c in s.scalars(select(PipelineCard))}
    for u in users:
        sync_pipeline.delay(u)
    return sorted(users)


@app.task(name="worker.tasks.retry_queued")
def retry_queued():
    from agent import health
    from apps.api.db import JobRow, session
    if "marketplace" in health.degraded():
        return []
    with session() as s:
        q = [(r.user_id, r.job_id) for r in s.scalars(select(JobRow).where(JobRow.status == "queued"))]
    for u, j in q[:50]:
        run_bid.delay(u, j)
    return q
