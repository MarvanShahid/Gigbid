import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent import health
from agent.graphs import bid_graph, conversation_graph
from agent.mcp_client import Gateway, ToolUnavailable, set_gateway
from agent.runtime import pending_interrupt, thread_config
from mcp_servers.marketplace.approvals import mint
from tests.fixtures import user_ctx
from tests.integration.test_bid_graph import load, pick

H = {"Authorization": "Bearer gigsim-dev-marvan"}


async def submit_good_proposal(sim, store):
    """Submit until a client replies (the simulated client decides)."""
    for job in [j for j in __import__("tests.integration.test_bid_graph", fromlist=["DEV"]).DEV
                if j["_gold"]["bid"] and not j["_gold"]["injected"]][:12]:
        load(sim, [job])
        g = bid_graph.build(InMemorySaver(), store)
        cfg = thread_config("bid", "marvan", job["id"])
        await g.ainvoke({"job_id": job["id"], "user": user_ctx(), "trace_id": "c"}, cfg)
        p = pending_interrupt(await g.aget_state(cfg))
        if not p:
            continue
        pv = p["preview"]
        grant = mint("marvan", "submit_proposal", {k: pv[k] for k in ("job_id", "cover_letter", "bid_amount", "answers")},
                     "g-" + job["id"])
        await g.ainvoke(Command(resume={"action": "approve", "grant": grant}), cfg)
        threads = httpx.get(f"{sim}/messages", headers=H).json()["threads"]
        if threads:
            return threads[0]
    pytest.skip("no simulated client replied")


@pytest.mark.asyncio
async def test_client_reply_drafted_approved_sent(sim, fresh_store):
    t = await submit_good_proposal(sim, fresh_store)
    g = conversation_graph.build(InMemorySaver(), fresh_store)
    cfg = thread_config("conv", "marvan", t["id"])
    await g.ainvoke({"thread_id": t["id"], "user": user_ctx(), "trace_id": "conv"}, cfg)
    p = pending_interrupt(await g.aget_state(cfg))
    assert p and p["kind"] == "message" and p["reply"]["text"]
    grant = mint("marvan", "send_message", {"thread_id": t["id"], "text": p["reply"]["text"]}, "m-1")
    out = await g.ainvoke(Command(resume={"action": "approve", "grant": grant,
                                          "slot": (p["slots"] or [None])[0]}), cfg)
    assert out["status"] == "sent"
    msgs = httpx.get(f"{sim}/messages", headers=H).json()["threads"][0]["messages"]
    assert any(m["from"] == "freelancer" for m in msgs)


@pytest.mark.asyncio
async def test_scam_message_gets_safe_reply(sim, fresh_store, monkeypatch):
    from agent.nodes import liaison
    st = {"thread_id": "t1", "user": user_ctx(), "last_client_message": "Let's continue on Telegram @payfast, "
          "and pay the registration fee first.", "thread": {"messages": []}}
    out = await liaison.classify(st)
    assert out["intent"]["intent"] == "scam_signal"
    rep = liaison.reply_rules({**st, **out})
    assert "on this platform" in rep.text


@pytest.mark.asyncio
async def test_marketplace_down_degrades_and_recovers(sim, fresh_store):
    gw = Gateway()
    gw.retries, gw.backoff = 1, 0.01
    gw.down.add("marketplace")                 # "kill the marketplace MCP server"
    set_gateway(gw)
    job = pick(bid=True, scam=False, injected=False)
    load(sim, [job])
    g = bid_graph.build(InMemorySaver(), fresh_store)
    cfg = thread_config("bid", "marvan", job["id"])
    with pytest.raises(ToolUnavailable):
        await g.ainvoke({"job_id": job["id"], "user": user_ctx(), "trace_id": "deg"}, cfg)
    assert "marketplace" in health.degraded()
    gw.down.clear()                             # server back: resume the same thread from its checkpoint
    out = await g.ainvoke(None, cfg)
    assert out.get("decision") and "marketplace" not in health.degraded()
    set_gateway(None)


@pytest.mark.asyncio
async def test_allowlist_enforced():
    from agent.mcp_client import ToolNotAllowed
    with pytest.raises(ToolNotAllowed):
        await Gateway().call("risk", "submit_proposal", {})


@pytest.mark.asyncio
async def test_step_budget_moves_thread_to_needs_attention(sim, fresh_store, monkeypatch):
    from agent import settings
    cfg_ = settings.config()
    monkeypatch.setitem(cfg_["budgets"], "max_steps_per_thread", 3)
    job = pick(bid=True, scam=False, injected=False)
    load(sim, [job])
    g = bid_graph.build(InMemorySaver(), fresh_store)
    out = await g.ainvoke({"job_id": job["id"], "user": user_ctx(), "trace_id": "bud"},
                          thread_config("bid", "marvan", job["id"]))
    assert out["status"] == "needs_attention"


@pytest.mark.asyncio
async def test_change_request_policy_v2(sim, fresh_store):
    """2 Nov policy update: large-budget jobs cost 1.5x Connects; unanswered screening questions are rejected."""
    httpx.post(f"{sim}/admin/policy/2", headers={"x-admin-key": "sim-admin"})
    job = next(j for j in __import__("tests.integration.test_bid_graph", fromlist=["DEV"]).DEV
               if j["_gold"]["bid"] and j["budget"]["amount"] >= 2000 and not j["_gold"]["injected"])
    load(sim, [job])
    g = bid_graph.build(InMemorySaver(), fresh_store)
    cfg = thread_config("bid", "marvan", job["id"])
    out = await g.ainvoke({"job_id": job["id"], "user": user_ctx(), "trace_id": "cr"}, cfg)
    assert out["price"]["connects_cost"] == round(job["connects_required"] * 1.5)
    assert any("policy v2" in r for r in out["price"]["rationale"])
