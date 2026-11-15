"""GigSim stand-in: a small marketplace simulator.

The instructor's GigSim was not available, so this service imitates the parts
GigBid depends on: jobs (with a slowly released live stream), clients with
histories and *hidden* preferences, Connects, proposals, messages, per-token
rate limits, random 5xx errors and a policy update (the change request).

Simulated clients are rule-based, not an LLM: they reply when a proposal covers
their requirements with specific evidence, avoids a generic opening, stays near
their budget and is not too long. Everything is deterministic given the seed.

Run:  uvicorn sim.app:app --port 8100
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

SEED_DIR = Path(__file__).parent / "seed"
RATE_LIMIT = int(os.getenv("SIM_RATE_LIMIT_PER_MIN", "60"))
ERROR_RATE = float(os.getenv("SIM_ERROR_RATE", "0.03"))
INITIAL_VISIBLE = int(os.getenv("SIM_INITIAL_JOBS", "80"))
START_CONNECTS = int(os.getenv("SIM_START_CONNECTS", "200"))

GENERIC_OPENERS = re.compile(
    r"(?i)(dear hiring manager|i am the perfect fit|passionate|i have read your job post|"
    r"i am very interested|to whom it may concern|hello sir)")

POLICY = {
    1: {"version": 1, "effective": "2026-10-27", "summary": "Base rules.",
        "connects_multiplier_large_budget": 1.0, "requires_all_screening_answers": False},
    2: {"version": 2, "effective": "2026-11-02",
        "summary": "Platform policy update: jobs with a budget of $2000 or more cost 50% more Connects, and a "
                   "proposal that leaves any screening question unanswered is rejected.",
        "connects_multiplier_large_budget": 1.5, "requires_all_screening_answers": True},
}


class World:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.reset()

    def reset(self, seed: int = 800) -> None:
        with self.lock:
            self.rng = random.Random(seed)
            self.jobs: list[dict] = json.loads((SEED_DIR / "live_jobs.json").read_text())
            self.clients = {c["id"]: c for c in json.loads((SEED_DIR / "clients.json").read_text())}
            self.history = json.loads((SEED_DIR / "job_history.json").read_text())
            self.extra_jobs: dict[str, dict] = {}  # jobs injected by evals
            self.visible = INITIAL_VISIBLE
            self.connects: dict[str, int] = defaultdict(lambda: START_CONNECTS)
            self.proposals: dict[str, dict] = {}
            self.idem: dict[tuple[str, str], Any] = {}
            self.threads: dict[str, dict] = {}
            self.policy_version = int(os.getenv("SIM_POLICY_VERSION", "1"))
            self.calls: dict[str, deque] = defaultdict(deque)
            self.error_rate = ERROR_RATE

    # ---------------------------------------------------------------- helpers
    def job(self, jid: str) -> dict | None:
        if jid in self.extra_jobs:
            return self.extra_jobs[jid]
        for j in self.jobs[: self.visible]:
            if j["id"] == jid:
                return j
        return None

    def connects_cost(self, job: dict) -> int:
        p = POLICY[self.policy_version]
        base = job["connects_required"]
        if job["budget"]["amount"] >= 2000:
            base = int(round(base * p["connects_multiplier_large_budget"]))
        return base


CANON: dict[str, str] = json.loads((SEED_DIR / "skill_names.json").read_text())
W = World()
app = FastAPI(title="GigSim stand-in", version="1.0")


def public_job(j: dict) -> dict:
    out = {k: v for k, v in j.items() if not k.startswith("_")}
    out["connects_required"] = W.connects_cost(j)
    return out


def public_client(c: dict) -> dict:
    return {k: v for k, v in c.items() if k not in ("risk",) and not k.startswith("_")}


def auth(request: Request, authorization: str = Header(default="")) -> str:
    if not authorization.startswith("Bearer ") or len(authorization) < 12:
        raise HTTPException(401, "missing or invalid bearer token")
    token = authorization[7:]
    user = hashlib.sha256(token.encode()).hexdigest()[:12]
    now = time.time()
    with W.lock:
        q = W.calls[user]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= RATE_LIMIT:
            raise HTTPException(429, "rate limit exceeded", headers={"Retry-After": str(int(60 - (now - q[0])) + 1)})
        q.append(now)
        if request.method == "GET" and W.rng.random() < W.error_rate:
            raise HTTPException(503, "simulated upstream error")
    return user


@app.get("/health")
def health() -> dict:
    return {"ok": True, "policy_version": W.policy_version, "visible_jobs": W.visible}


@app.get("/policy")
def policy(user: str = Depends(auth)) -> dict:
    return POLICY[W.policy_version]


@app.get("/jobs")
def search_jobs(q: str = "", category: str | None = None, limit: int = 20, offset: int = 0,
                min_budget: int = 0, user: str = Depends(auth)) -> dict:
    with W.lock:
        pool = W.jobs[: W.visible] + list(W.extra_jobs.values())
        terms = [t for t in re.split(r"\W+", q.lower()) if t]
        hits = []
        for j in pool:
            text = (j["title"] + " " + j["description"] + " " + " ".join(j["skills_tags"])).lower()
            if terms and not any(t in text for t in terms):
                continue
            if category and j["category"] != category:
                continue
            if j["budget"]["amount"] < min_budget:
                continue
            hits.append(public_job(j))
        hits.sort(key=lambda j: j["posted_at"], reverse=True)
        return {"total": len(hits), "jobs": hits[offset: offset + min(limit, 50)]}


@app.get("/jobs/{job_id}")
def get_job(job_id: str, user: str = Depends(auth)) -> dict:
    j = W.job(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    return public_job(j)


@app.get("/clients/{client_id}")
def get_client(client_id: str, user: str = Depends(auth)) -> dict:
    c = W.clients.get(client_id)
    if not c:
        raise HTTPException(404, "client not found")
    return public_client(c)


@app.get("/market/stats")
def market_stats(category: str, user: str = Depends(auth)) -> dict:
    rows = [h["awarded"] for h in W.history if h["category"] == category]
    if not rows:
        raise HTTPException(404, "unknown category")
    rows.sort()
    pct = lambda p: rows[min(len(rows) - 1, int(p * len(rows)))]  # noqa: E731
    return {"category": category, "n": len(rows), "p25": pct(.25), "median": pct(.5), "p75": pct(.75)}


@app.get("/connects")
def connects(user: str = Depends(auth)) -> dict:
    return {"balance": W.connects[user]}


class ProposalIn(BaseModel):
    job_id: str
    cover_letter: str = Field(min_length=40, max_length=5000)
    bid_amount: float = Field(gt=0)
    answers: list[str] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=8, max_length=128)


def _client_decision(job: dict, client: dict, p: ProposalIn, pid: str) -> dict:
    hidden = client["_hidden"]
    gold = job.get("_gold", {})
    reqs = [r for r in gold.get("requirements", [])]
    text = p.cover_letter
    lower = text.lower()
    named = [r for r in reqs if CANON.get(r, r).lower() in lower]
    coverage = len(named) / max(1, len(reqs))
    score = (2.0 if hidden["wants_evidence"] else 1.0) * coverage
    first = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]
    generic = bool(GENERIC_OPENERS.search(first))
    if generic and hidden["dislikes_generic_opening"]:
        score -= 1.5
    budget = job["budget"]["amount"]
    score += 0.5 if p.bid_amount <= budget * hidden["budget_tolerance"] else -1.5
    words = len(text.split())
    score += 0.3 if words <= hidden["max_words"] else -0.7
    score += 1.0 if gold.get("bid") else -1.0
    noise = (int(hashlib.sha256(pid.encode()).hexdigest()[:6], 16) / 0xFFFFFF) - 0.5
    score += noise
    replied = score >= 1.6
    hired = replied and score >= 2.6
    return {"score": round(score, 3), "replied": replied, "hired": hired, "coverage": round(coverage, 2),
            "generic_opening": generic, "words": words}


@app.post("/proposals")
def submit_proposal(p: ProposalIn, user: str = Depends(auth)) -> dict:
    with W.lock:
        key = (user, p.idempotency_key)
        if key in W.idem:
            return {**W.idem[key], "idempotent_replay": True}
        job = W.job(p.job_id)
        if not job:
            raise HTTPException(404, "job not found")
        pol = POLICY[W.policy_version]
        if pol["requires_all_screening_answers"] and len([a for a in p.answers if a.strip()]) < len(
                job["screening_questions"]):
            raise HTTPException(400, "policy v2: every screening question must be answered")
        cost = W.connects_cost(job)
        if W.connects[user] < cost:
            raise HTTPException(402, "not enough Connects")
        W.connects[user] -= cost
        pid = "p" + hashlib.sha256(f"{user}:{p.idempotency_key}".encode()).hexdigest()[:10]
        client = W.clients[job["client_id"]]
        decision = _client_decision(job, client, p, pid)
        status = "hired" if decision["hired"] else "replied" if decision["replied"] else "viewed" \
            if decision["score"] > 0.5 else "submitted"
        prop = {"id": pid, "job_id": p.job_id, "user": user, "bid_amount": p.bid_amount, "connects_spent": cost,
                "status": status, "submitted_at": time.time(), "_decision": decision}
        W.proposals[pid] = prop
        if decision["replied"]:
            tid = "t" + pid[1:]
            W.threads[tid] = {"id": tid, "proposal_id": pid, "client_id": client["id"], "user": user, "messages": [
                {"from": "client", "text": _client_opening(job, decision), "at": time.time()}]}
        out = {"proposal_id": pid, "status": "submitted", "connects_spent": cost, "balance": W.connects[user]}
        W.idem[key] = out
        return out


def _client_opening(job: dict, d: dict) -> str:
    if d["hired"]:
        return (f"Thanks for the proposal on '{job['title']}'. Could we do a 30 minute call this week? "
                f"Please share a couple of time slots.")
    return f"Hi, thanks for applying to '{job['title']}'. What would your first milestone include and how long would it take?"


@app.get("/proposals")
def list_proposals(user: str = Depends(auth)) -> dict:
    return {"proposals": [{k: v for k, v in p.items() if not k.startswith("_")}
                          for p in W.proposals.values() if p["user"] == user]}


@app.get("/proposals/{pid}")
def get_proposal(pid: str, user: str = Depends(auth)) -> dict:
    p = W.proposals.get(pid)
    if not p or p["user"] != user:
        raise HTTPException(404, "proposal not found")
    return {k: v for k, v in p.items() if not k.startswith("_")}


@app.get("/messages")
def list_messages(user: str = Depends(auth)) -> dict:
    return {"threads": [t for t in W.threads.values() if t["user"] == user]}


class MessageIn(BaseModel):
    thread_id: str
    text: str = Field(min_length=1, max_length=3000)
    idempotency_key: str = Field(min_length=8, max_length=128)


@app.post("/messages")
def send_message(m: MessageIn, user: str = Depends(auth)) -> dict:
    with W.lock:
        key = (user, m.idempotency_key)
        if key in W.idem:
            return {**W.idem[key], "idempotent_replay": True}
        t = W.threads.get(m.thread_id)
        if not t or t["user"] != user:
            raise HTTPException(404, "thread not found")
        t["messages"].append({"from": "freelancer", "text": m.text, "at": time.time()})
        prop = W.proposals[t["proposal_id"]]
        slots = re.findall(r"\b(mon|tue|wed|thu|fri|sat|sun)\w*\b", m.text.lower())
        if slots and prop["status"] in ("replied", "hired"):
            t["messages"].append({"from": "client", "text": "The first slot works. Talk then.", "at": time.time()})
            prop["status"] = "interview" if prop["status"] == "replied" else "hired"
        elif prop["status"] == "replied":
            t["messages"].append({"from": "client", "text": "Sounds reasonable. Can you suggest times for a short call?",
                                  "at": time.time()})
        out = {"ok": True, "thread_id": m.thread_id}
        W.idem[key] = out
        return out


# ------------------------------------------------------------------ admin (dev/eval only)
def admin(x_admin_key: str = Header(default="")) -> None:
    if x_admin_key != os.getenv("SIM_ADMIN_KEY", "sim-admin"):
        raise HTTPException(403, "admin only")


@app.post("/admin/reset", dependencies=[Depends(admin)])
def admin_reset(seed: int = 800, error_rate: float | None = None) -> dict:
    W.reset(seed)
    if error_rate is not None:
        W.error_rate = error_rate
    return {"ok": True}


@app.post("/admin/advance", dependencies=[Depends(admin)])
def admin_advance(n: int = 10) -> dict:
    W.visible = min(len(W.jobs), W.visible + n)
    return {"visible": W.visible}


@app.post("/admin/policy/{version}", dependencies=[Depends(admin)])
def admin_policy(version: int) -> dict:
    if version not in POLICY:
        raise HTTPException(404, "unknown policy")
    W.policy_version = version
    return POLICY[version]


@app.post("/admin/jobs", dependencies=[Depends(admin)])
def admin_add_jobs(jobs: list[dict]) -> dict:
    """Load labelled jobs (e.g. the dev set) so the eval runner can measure reply rate on a fixed set."""
    for j in jobs:
        W.extra_jobs[j["id"]] = j
    return {"loaded": len(jobs)}


@app.post("/admin/error_rate", dependencies=[Depends(admin)])
def admin_error_rate(rate: float) -> dict:
    W.error_rate = rate
    return {"error_rate": rate}


@app.exception_handler(HTTPException)
async def http_exc(_: Request, exc: HTTPException):  # keep Retry-After header
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
