"""Analytics: reply/hire rate by category, Connects vs outcomes, cost and latency, rejection reasons."""
from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np
from fastapi import APIRouter
from sqlalchemy import select

from apps.api.auth.security import CurrentUser
from apps.api.db import JobRow, PipelineCard, Rejection, Run, session

router = APIRouter(prefix="/api/analytics", tags=["analytics"])
SUCCESS = {"replied", "interview", "hired"}


@router.get("")
def analytics(user: str = CurrentUser) -> dict:
    with session() as s:
        cards = list(s.scalars(select(PipelineCard).where(PipelineCard.user_id == user)))
        jobs = list(s.scalars(select(JobRow).where(JobRow.user_id == user)))
        runs = list(s.scalars(select(Run).where(Run.user_id == user)))
        rej = list(s.scalars(select(Rejection).where(Rejection.user_id == user)))
    sent = [c for c in cards if c.stage != "drafted"]
    by_cat: dict[str, dict] = defaultdict(lambda: {"sent": 0, "replied": 0, "hired": 0, "connects": 0})
    for c in sent:
        d = by_cat[c.category or "unknown"]
        d["sent"] += 1
        d["replied"] += c.stage in SUCCESS
        d["hired"] += c.stage == "hired"
        d["connects"] += c.connects
    cats = [{"category": k, **v, "reply_rate": v["replied"] / v["sent"], "hire_rate": v["hired"] / v["sent"]}
            for k, v in sorted(by_cat.items())]
    bid_runs = [r for r in runs if r.kind == "bid" and r.finished]
    lat = [r.finished - r.started for r in bid_runs]
    per_prop = [c.cost_usd for c in cards if c.stage != "drafted"]
    return {
        "totals": {"jobs_seen": len(jobs), "analysed": sum(j.fit is not None for j in jobs),
                   "recommended_bid": sum(j.recommendation == "bid" for j in jobs),
                   "skipped": sum(j.status == "skipped" for j in jobs),
                   "scams_caught": sum(bool(((j.summary or {}).get("risk") or {}).get("is_scam")) for j in jobs),
                   "proposals_sent": len(sent), "replies": sum(c.stage in SUCCESS for c in sent),
                   "hires": sum(c.stage == "hired" for c in sent),
                   "connects_spent": sum(c.connects for c in sent)},
        "by_category": cats,
        "connects_vs_outcomes": [{"category": c["category"], "connects": c["connects"], "replies": c["replied"]}
                                 for c in cats],
        "latency": {"p50_s": float(np.percentile(lat, 50)) if lat else None,
                    "p95_s": float(np.percentile(lat, 95)) if lat else None, "n": len(lat)},
        "cost": {"usd_per_job": (sum(r.cost_usd for r in bid_runs) / len(bid_runs)) if bid_runs else 0.0,
                 "usd_per_proposal": (sum(per_prop) / len(per_prop)) if per_prop else 0.0},
        "top_rejection_reasons": Counter(r.reason for r in rej).most_common(5),
    }
