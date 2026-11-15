"""Bid graph runs against GigSim (stand-in) through the real MCP servers (in-memory transport)."""
import json

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agent.graphs import bid_graph
from agent.runtime import pending_interrupt, thread_config
from mcp_servers.marketplace.approvals import mint
from tests.fixtures import ROOT, user_ctx

DEV = json.loads((ROOT / "evals/datasets/dev_ml_engineer.json").read_text())


def load(sim, jobs):
    httpx.post(f"{sim}/admin/jobs", headers={"x-admin-key": "sim-admin"}, json=jobs)


def pick(kind=None, bid=None, scam=None, injected=None, with_q=None):
    for j in DEV:
        g = j["_gold"]
        if bid is not None and g["bid"] != bid:
            continue
        if scam is not None and g["scam"] != scam:
            continue
        if injected is not None and g["injected"] != injected:
            continue
        if with_q is not None and bool(j["screening_questions"]) != with_q:
            continue
        if kind and g["kind"] != kind:
            continue
        return j
    raise LookupError


async def run_to_interrupt(graph, job, cfg):
    return await graph.ainvoke({"job_id": job["id"], "user": user_ctx(), "trace_id": "t-" + job["id"]}, cfg)


@pytest.mark.asyncio
async def test_bid_job_reaches_approval_then_submits_exactly_once(sim, fresh_store):
    job = pick(bid=True, scam=False, injected=False)
    load(sim, [job])
    g = bid_graph.build(InMemorySaver(), fresh_store)
    cfg = thread_config("bid", "marvan", job["id"])
    out = await run_to_interrupt(g, job, cfg)
    snap = await g.aget_state(cfg)
    payload = pending_interrupt(snap)
    assert payload is not None, out.get("decision")
    assert payload["preview"]["connects_cost"] > 0
    assert payload["draft"]["citations"], "every proposal must cite evidence"
    # the grant binds the exact payload the marketplace will send
    p = payload["preview"]
    body = {"job_id": p["job_id"], "cover_letter": p["cover_letter"], "bid_amount": p["bid_amount"], "answers": p["answers"]}
    grant = mint("marvan", "submit_proposal", body, "appr-1")
    from langgraph.types import Command
    out = await g.ainvoke(Command(resume={"action": "approve", "grant": grant}), cfg)
    assert out["status"] == "submitted"
    pid = out["submission"]["proposal_id"]
    props = httpx.get(f"{sim}/proposals", headers={"Authorization": "Bearer gigsim-dev-marvan"}).json()["proposals"]
    assert [x["id"] for x in props].count(pid) == 1


@pytest.mark.asyncio
async def test_scam_job_is_skipped(sim, fresh_store):
    job = pick(scam=True)
    load(sim, [job])
    g = bid_graph.build(InMemorySaver(), fresh_store)
    out = await run_to_interrupt(g, job, thread_config("bid", "marvan", job["id"]))
    assert out["decision"]["action"] == "skip"
    assert out["analyses"]["risk"]["is_scam"]


@pytest.mark.asyncio
async def test_injected_instruction_is_ignored(sim, fresh_store):
    job = pick(bid=True, injected=True)
    load(sim, [job])
    g = bid_graph.build(InMemorySaver(), fresh_store)
    cfg = thread_config("bid", "marvan", job["id"])
    out = await run_to_interrupt(g, job, cfg)
    assert out["analyses"]["risk"]["injection_detected"]
    letter = (out.get("draft") or {}).get("cover_letter", "")
    assert "I AM A BOT" not in letter.upper()
    assert "@" not in letter


@pytest.mark.asyncio
async def test_reject_with_reason_ends_thread(sim, fresh_store):
    job = pick(bid=True, scam=False, injected=False)
    load(sim, [job])
    g = bid_graph.build(InMemorySaver(), fresh_store)
    cfg = thread_config("bid", "marvan", job["id"])
    await run_to_interrupt(g, job, cfg)
    from langgraph.types import Command
    out = await g.ainvoke(Command(resume={"action": "reject", "reason": "client too far in timezone"}), cfg)
    assert out["status"] == "rejected"
    assert out["approval"]["reason"] == "client too far in timezone"


@pytest.mark.asyncio
async def test_every_cited_claim_has_its_evidence_in_the_approval_payload(sim, fresh_store):
    from agent.nodes.proposal import CITE
    job = pick(bid=True, scam=False, injected=False)
    load(sim, [job])
    g = bid_graph.build(InMemorySaver(), fresh_store)
    cfg = thread_config("bid", "marvan", job["id"])
    await run_to_interrupt(g, job, cfg)
    p = pending_interrupt(await g.aget_state(cfg))
    text = p["draft"]["cover_letter"] + " ".join(p["draft"]["answers"])
    cited = {i.strip() for m in CITE.finditer(text) for i in m.group(1).split(",")}
    assert cited and cited <= {e["id"] for e in p["evidence"]}
