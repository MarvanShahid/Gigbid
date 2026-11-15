"""Scripted demo for the video (no UI needed): one job inbox -> approved proposal, one scam caught,
one injected instruction ignored, one client reply handled.

    python scripts/demo.py           (rules profile; set GIGBID_PROFILE=open + GROQ_API_KEY for model-written drafts)
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SIM_START_CONNECTS", "100000")


async def main() -> None:
    import httpx
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    from agent.graphs import bid_graph, conversation_graph
    from agent.runtime import pending_interrupt, thread_config
    from evals.runners.common import dev_set, setup_env, start_sim
    from mcp_servers.marketplace.approvals import mint
    setup_env(os.getenv("GIGBID_PROFILE", "rules"))
    sim = start_sim()
    dev = [j for j in dev_set("ml_engineer") if "-dup" not in j["id"]]
    good = [j for j in dev if j["_gold"]["bid"] and not j["_gold"]["injected"]][:8]
    scam = next(j for j in dev if j["_gold"]["scam"])
    inj = next(j for j in dev if j["_gold"]["injected"])
    httpx.post(f"{sim}/admin/jobs", headers={"x-admin-key": "sim-admin"}, json=good + [scam, inj])
    user = {"account": "demo", "owner": "ml_engineer", "hourly_floor": 35, "hourly_rate": 45, "autonomy": "suggest"}
    g = bid_graph.build(InMemorySaver())
    print("\n== 1. scam ==")
    out = await g.ainvoke({"job_id": scam["id"], "user": user, "trace_id": "demo-scam"}, thread_config("bid", "demo", scam["id"]))
    print(out["decision"], [f["evidence"] for f in out["analyses"]["risk"]["flags"]])
    print("\n== 2. injected instruction ==")
    print("post contains:", [ln for ln in inj["description"].splitlines() if "AI" in ln or "SYSTEM" in ln or "assistant" in ln.lower()])
    out = await g.ainvoke({"job_id": inj["id"], "user": user, "trace_id": "demo-inj"}, thread_config("bid", "demo", inj["id"]))
    print("detected:", out["analyses"]["risk"]["injection_detected"], "| decision:", out["decision"]["action"])
    print("\n== 3. inbox -> approved proposal (until a client replies) ==")
    for job in good:
        cfg = thread_config("bid", "demo", job["id"])
        await g.ainvoke({"job_id": job["id"], "user": user, "trace_id": f"demo-{job['id']}"}, cfg)
        p = pending_interrupt(await g.aget_state(cfg))
        if not p:
            continue
        print(job["title"], "->", p["draft"]["cover_letter"][:300], "...")
        pv = p["preview"]
        grant = mint("demo", "submit_proposal", {k: pv[k] for k in ("job_id", "cover_letter", "bid_amount", "answers")}, job["id"])
        out = await g.ainvoke(Command(resume={"action": "approve", "grant": grant}), cfg)
        print("submitted:", out["submission"])
        threads = httpx.get(f"{sim}/messages", headers={"Authorization": "Bearer gigsim-dev-demo"}).json()["threads"]
        if threads:
            break
    print("\n== 4. client reply ==")
    t = threads[0]
    print("client:", t["messages"][-1]["text"])
    c = conversation_graph.build(InMemorySaver())
    cfg = thread_config("conv", "demo", t["id"])
    await c.ainvoke({"thread_id": t["id"], "user": user, "trace_id": "demo-conv"}, cfg)
    p = pending_interrupt(await c.aget_state(cfg))
    print("intent:", p["intent"]["intent"], "| suggested reply:", p["reply"]["text"])
    grant = mint("demo", "send_message", {"thread_id": t["id"], "text": p["reply"]["text"]}, "demo-msg")
    out = await c.ainvoke(Command(resume={"action": "approve", "grant": grant, "slot": (p["slots"] or [None])[0]}), cfg)
    print("sent:", out["status"])


if __name__ == "__main__":
    asyncio.run(main())
