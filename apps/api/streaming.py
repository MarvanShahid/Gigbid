"""SSE bridge to LangGraph streams.

Graph runs (in the worker or in-process) write one event per node update into
runs.events. The SSE endpoint replays stored events and then tails new ones, so a
page refresh never loses progress and it works whether the run is in this
process or in the Celery worker."""
from __future__ import annotations

import asyncio
import json
import time

from sse_starlette.sse import EventSourceResponse

from apps.api.db import Run, session

NODE_LABEL = {
    "scout_in": "Scout handed the job in", "analyst": "Job Analyst extracted the JobSpec",
    "risk": "Risk Assessor checked scam / injection signals", "researcher": "Client Researcher built the client brief",
    "matcher": "Fit Matcher mapped requirements to evidence", "decide": "Decision", "pricing": "Pricing Strategist",
    "writer": "Proposal Writer drafted", "verifier": "Claim verification", "critic": "Critic reviewed",
    "compliance": "Compliance Guard", "preview": "Dry-run preview", "approval": "Waiting for your approval",
    "submit": "Submitted to the marketplace", "finish": "Done", "needs_attention": "Needs attention",
    "read_thread": "Read the client thread", "intent": "Classified intent", "slots": "Found interview slots",
    "draft_reply": "Drafted a reply", "reply_compliance": "Compliance Guard", "approve_reply": "Waiting for your approval",
    "send": "Message sent", "end": "Done",
}


def summarise(node: str, upd: dict) -> str:
    a = (upd or {}).get("analyses") or {}
    try:
        if node == "analyst":
            return f"{len(a['spec']['requirements'])} requirements, budget ${a['spec']['budget_amount']:,.0f}"
        if node == "risk":
            r = a["risk"]
            return f"risk {r['level']} ({r['score']:.2f})" + (" - injection removed" if r.get("injection_detected") else "")
        if node == "researcher":
            return "; ".join(a["brief"]["signals"][:2])
        if node == "matcher":
            return f"fit {a['fit']['score']:.2f}, {len(upd.get('evidence', []))} evidence items"
        if node == "decide":
            return f"{upd['decision']['action'].upper()}: {upd['decision']['reasons'][0]}"
        if node == "pricing":
            return f"${upd['price']['amount']:,.0f}, {upd['price']['connects_cost']} Connects"
        if node == "writer":
            return f"{len(upd['draft']['cover_letter'].split())} words, {len(upd['draft']['citations'])} cited claims"
        if node == "verifier":
            v = upd["verification"]
            return f"unsupported claims {v['unsupported_before']} -> {v['unsupported_after']} of {v['claims_before']}"
        if node == "critic":
            c = upd["critiques"][-1]
            return ("passed" if c["passed"] else "sent back: " + "; ".join(i["detail"] for i in c["issues"][:2]))
        if node in ("compliance", "reply_compliance"):
            c = upd["compliance"]
            return c["status"] + (f" ({c.get('reason')})" if c.get("reason") else "")
        if node == "intent":
            return upd["intent"]["intent"]
    except (KeyError, TypeError, IndexError):
        pass
    return upd.get("status", "") if isinstance(upd, dict) and isinstance(upd.get("status"), str) else ""


def record(run_id: str, node: str, upd: dict | None, kind: str = "node") -> None:
    ev = {"t": time.time(), "kind": kind, "node": node, "label": NODE_LABEL.get(node, node),
          "detail": summarise(node, upd or {}) if kind == "node" else (upd or {}).get("detail", "")}
    with session() as s:
        r = s.get(Run, run_id)
        if r:
            r.events = [*(r.events or []), ev]


async def sse(run_id: str, user_id: str) -> EventSourceResponse:
    async def gen():
        sent = 0
        idle = 0
        while True:
            with session() as s:
                r = s.get(Run, run_id)
                if not r or r.user_id != user_id:
                    yield {"event": "error", "data": json.dumps({"detail": "run not found"})}
                    return
                events, status = list(r.events or []), r.status
            for ev in events[sent:]:
                yield {"event": "node", "data": json.dumps(ev)}
            idle = 0 if len(events) > sent else idle + 1
            sent = len(events)
            if status not in ("running", "queued"):
                yield {"event": "done", "data": json.dumps({"status": status})}
                return
            if idle > 1200:   # 10 minutes without progress
                return
            await asyncio.sleep(0.5)
    return EventSourceResponse(gen(), ping=10)
