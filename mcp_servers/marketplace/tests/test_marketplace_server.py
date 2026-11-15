"""Marketplace MCP server through an in-memory MCP client."""
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from mcp_servers.marketplace.approvals import mint
from mcp_servers.marketplace.server import mcp


async def call(name, args):
    async with create_connected_server_and_client_session(mcp) as s:
        return await s.call_tool(name, args)


@pytest.mark.asyncio
async def test_annotations_are_correct():
    async with create_connected_server_and_client_session(mcp) as s:
        tools = {t.name: t for t in (await s.list_tools()).tools}
    for n in ("search_jobs", "get_job", "get_client_history", "market_stats"):
        assert tools[n].annotations.readOnlyHint is True
    assert tools["submit_proposal"].annotations.destructiveHint is True
    assert tools["submit_proposal"].annotations.idempotentHint is True
    assert tools["create_proposal_draft"].annotations.readOnlyHint is False
    assert tools["submit_proposal"].outputSchema is not None


@pytest.mark.asyncio
async def test_schema_constraints_reject_bad_input(sim):
    r = await call("create_proposal_draft", {"account": "marvan", "job_id": "x", "cover_letter": "too short",
                                             "bid_amount": 10})
    assert r.isError
    r = await call("search_jobs", {"account": "bad account!", "limit": 5})
    assert r.isError


@pytest.mark.asyncio
async def test_dry_run_then_grant_then_idempotent_submit(sim):
    jobs = (await call("search_jobs", {"account": "marvan", "limit": 1})).structuredContent["jobs"]
    job = jobs[0]
    body = {"account": "marvan", "job_id": job["id"], "cover_letter": "A grounded proposal text " * 3,
            "bid_amount": 500.0, "answers": ["Yes."] * len(job["screening_questions"])}
    d = (await call("create_proposal_draft", body)).structuredContent
    dry = (await call("submit_proposal", {"account": "marvan", "draft_id": d["draft_id"],
                                          "idempotency_key": "k-12345678", "dry_run": True})).structuredContent
    assert dry["status"] == "dry_run" and dry["preview"]["connects_cost"] == job["connects_required"]
    # no grant -> refused
    r = await call("submit_proposal", {"account": "marvan", "draft_id": d["draft_id"], "idempotency_key": "k-12345678",
                                       "dry_run": False})
    assert r.isError and "approval_required" in r.content[0].text
    payload = {k: body[k] for k in ("job_id", "cover_letter", "bid_amount", "answers")}
    grant = mint("marvan", "submit_proposal", payload, "a-1")
    first = (await call("submit_proposal", {"account": "marvan", "draft_id": d["draft_id"],
                                            "idempotency_key": "k-12345678", "approval_grant": grant,
                                            "dry_run": False})).structuredContent
    again = (await call("submit_proposal", {"account": "marvan", "draft_id": d["draft_id"],
                                            "idempotency_key": "k-12345678", "approval_grant": grant,
                                            "dry_run": False})).structuredContent
    assert first["status"] == "submitted" and again["idempotent_replay"] is True
    assert first["proposal_id"] == again["proposal_id"]


@pytest.mark.asyncio
async def test_grant_for_other_text_is_refused(sim):
    job = (await call("search_jobs", {"account": "marvan", "limit": 1})).structuredContent["jobs"][0]
    body = {"account": "marvan", "job_id": job["id"], "cover_letter": "The text the user really approved, long enough.",
            "bid_amount": 400.0, "answers": []}
    d = (await call("create_proposal_draft", body)).structuredContent
    grant = mint("marvan", "submit_proposal", {"job_id": job["id"], "cover_letter": "something else entirely here",
                                               "bid_amount": 400.0, "answers": []}, "a-2")
    r = await call("submit_proposal", {"account": "marvan", "draft_id": d["draft_id"], "idempotency_key": "k-abcdefgh",
                                       "approval_grant": grant, "dry_run": False})
    assert r.isError and "differs" in r.content[0].text


def test_audit_log_is_chained(sim):
    from mcp_servers.marketplace.server import AUDIT
    assert AUDIT.records(), "calls above must be audited"
    assert AUDIT.verify()
    assert all("trace_id" in r for r in AUDIT.records())
