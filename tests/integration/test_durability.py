"""C6: kill the process while a proposal waits for approval, restart, approve -> submitted exactly once.
Also: a crash *inside* submit (after the marketplace accepted it) is replayed safely."""

import httpx
import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from agent.graphs import bid_graph
from agent.runtime import pending_interrupt, thread_config
from mcp_servers.marketplace.approvals import mint
from tests.fixtures import user_ctx
from tests.integration.test_bid_graph import load, pick


def grant_for(payload, jti):
    p = payload["preview"]
    return mint("marvan", "submit_proposal", {"job_id": p["job_id"], "cover_letter": p["cover_letter"],
                                              "bid_amount": p["bid_amount"], "answers": p["answers"]}, jti)


def my_proposals(sim):
    return httpx.get(f"{sim}/proposals", headers={"Authorization": "Bearer gigsim-dev-marvan"}).json()["proposals"]


@pytest.mark.asyncio
async def test_restart_while_waiting_for_approval(sim, fresh_store, tmp_path):
    job = pick(bid=True, scam=False, injected=False)
    load(sim, [job])
    db = str(tmp_path / "cp.db")
    cfg = thread_config("bid", "marvan", job["id"])
    async with AsyncSqliteSaver.from_conn_string(db) as cp:          # process 1
        g = bid_graph.build(cp, fresh_store)
        await g.ainvoke({"job_id": job["id"], "user": user_ctx(), "trace_id": "dur-1"}, cfg)
        payload = pending_interrupt(await g.aget_state(cfg))
        assert payload
    # process 1 is gone; process 2 starts from the same database
    async with AsyncSqliteSaver.from_conn_string(db) as cp:
        g = bid_graph.build(cp, fresh_store)
        snap = await g.aget_state(cfg)
        assert pending_interrupt(snap), "pending approval must survive the restart"
        out = await g.ainvoke(Command(resume={"action": "approve", "grant": grant_for(payload, "dur-a")}), cfg)
        assert out["status"] == "submitted"
        # a second resume (double click / retried request) must not submit again
        await g.ainvoke(Command(resume={"action": "approve", "grant": grant_for(payload, "dur-a")}), cfg)
    ids = [p["id"] for p in my_proposals(sim) if p["job_id"] == job["id"]]
    assert len(ids) == 1


@pytest.mark.asyncio
async def test_crash_after_marketplace_accepted_is_replayed_once(sim, fresh_store, tmp_path, monkeypatch):
    job = pick(bid=True, scam=False, injected=False, with_q=False)
    load(sim, [job])
    db = str(tmp_path / "cp2.db")
    cfg = thread_config("bid", "marvan", job["id"])
    from agent import marketplace_port
    real = marketplace_port.GigSimPort.submit
    crashed = {"n": 0}

    async def flaky(self, agent, draft_id, key, grant, dry_run):
        res = await real(self, agent, draft_id, key, grant, dry_run)
        if not dry_run and crashed["n"] == 0:
            crashed["n"] += 1
            raise RuntimeError("worker killed right after the marketplace accepted the proposal")
        return res

    monkeypatch.setattr(marketplace_port.GigSimPort, "submit", flaky)
    async with AsyncSqliteSaver.from_conn_string(db) as cp:
        g = bid_graph.build(cp, fresh_store)
        await g.ainvoke({"job_id": job["id"], "user": user_ctx(), "trace_id": "dur-2"}, cfg)
        payload = pending_interrupt(await g.aget_state(cfg))
        with pytest.raises(RuntimeError):
            await g.ainvoke(Command(resume={"action": "approve", "grant": grant_for(payload, "dur-b")}), cfg)
    async with AsyncSqliteSaver.from_conn_string(db) as cp:   # restart and continue the thread
        g = bid_graph.build(cp, fresh_store)
        out = await g.ainvoke(None, cfg)
        assert out["status"] == "submitted"
        assert out["submission"].get("idempotent_replay") is True
    assert len([p for p in my_proposals(sim) if p["job_id"] == job["id"]]) == 1


@pytest.mark.asyncio
async def test_replay_from_any_node(sim, fresh_store, tmp_path):
    job = pick(bid=True, scam=False, injected=False)
    load(sim, [job])
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "cp3.db")) as cp:
        g = bid_graph.build(cp, fresh_store)
        cfg = thread_config("bid", "marvan", job["id"])
        await g.ainvoke({"job_id": job["id"], "user": user_ctx(), "trace_id": "dur-3"}, cfg)
        history = [s async for s in g.aget_state_history(cfg)]
        before_decide = next(s for s in history if s.next == ("decide",))
        out = await g.ainvoke(None, before_decide.config)   # replay (fork) from the decide node
        assert out["decision"]["action"] in ("bid", "watch", "skip")
