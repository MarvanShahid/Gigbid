"""GigBid Marketplace MCP server: wraps GigSim with read and write tools.

Every write tool has: a Pydantic input schema with real constraints, a declared
output schema, correct annotations, an idempotency key, a dry_run preview, and
an approval grant check. Every call goes through a per-account rate limiter and
lands in the append-only audit log with its trace id.

    python -m mcp_servers.marketplace.server --port 8201      (streamable HTTP, bearer auth)
"""
from __future__ import annotations

import argparse
import hashlib
import os
from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from agent.settings import config
from mcp_servers.common import AuditLog, RateLimiter
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter, MarketplaceError
from mcp_servers.marketplace.approvals import GrantError, GrantLedger

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
DRAFT = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
SEND = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True)

mcp = FastMCP("gigbid-marketplace", instructions=(
    "Marketplace access for GigBid (GigSim). Reads are safe. Writes need an approval_grant minted by the GigBid UI "
    "after the human approved the exact text; call with dry_run=true first to get the preview."), stateless_http=True)

ADAPTER = GigSimAdapter()
AUDIT = AuditLog()
LIMIT = RateLimiter()
LEDGER = GrantLedger()

Account = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$", description="GigBid account (tenant) id")


def _call(account: str, tool: str, args: dict, fn):
    LIMIT.acquire(account)
    try:
        result = fn()
    except MarketplaceError as e:
        AUDIT.append(account, tool, args, {"error": e.kind, "message": str(e)}, ok=False)
        raise RuntimeError(f"[{e.kind}] {e}") from e
    except GrantError as e:
        AUDIT.append(account, tool, args, {"error": "approval", "message": str(e)}, ok=False)
        raise RuntimeError(f"[approval_required] {e}") from e
    AUDIT.append(account, tool, args, result if isinstance(result, dict) else {"n": len(result)})
    return result


# ------------------------------------------------------------------ schemas
class Budget(BaseModel):
    type: str
    amount: float


class Job(BaseModel):
    id: str
    title: str
    description: str
    category: str
    skills_tags: list[str]
    budget: Budget
    client_id: str
    screening_questions: list[str]
    posted_at: str
    connects_required: int


class JobList(BaseModel):
    total: int
    jobs: list[Job]


class ClientHistory(BaseModel):
    id: str
    name: str
    industry: str
    country: str
    payment_verified: bool
    jobs_posted: int
    hires: int
    total_spend: float
    avg_rating_given: float | None
    member_since: str


class ConnectsCost(BaseModel):
    job_id: str
    connects: int
    policy_version: int
    policy_summary: str


class MarketStats(BaseModel):
    category: str
    n: int
    p25: float
    median: float
    p75: float


class ProposalPreview(BaseModel):
    job_id: str
    cover_letter: str
    bid_amount: float
    answers: list[str]
    connects_cost: int
    balance_after: int | None


class DraftOut(BaseModel):
    draft_id: str
    preview: ProposalPreview


class SubmitOut(BaseModel):
    status: Literal["dry_run", "submitted"]
    preview: ProposalPreview
    proposal_id: str | None = None
    connects_spent: int | None = None
    idempotent_replay: bool = False


class MessageOut(BaseModel):
    status: Literal["dry_run", "sent"]
    thread_id: str
    text: str
    idempotent_replay: bool = False


# ------------------------------------------------------------------ read tools
@mcp.tool(annotations=READ, structured_output=True)
def search_jobs(account: str = Account, query: str = Field("", max_length=200),
                category: str | None = Field(None, max_length=40), limit: int = Field(20, ge=1, le=50),
                min_budget: float = Field(0, ge=0)) -> JobList:
    """Search open jobs by keywords / category / minimum budget. Newest first."""
    return _call(account, "search_jobs", locals(), lambda: ADAPTER.search_jobs(account, query, category, limit, min_budget))


@mcp.tool(annotations=READ, structured_output=True)
def get_job(account: str = Account, job_id: str = Field(min_length=1, max_length=64)) -> Job:
    """Full job post, including screening questions and the current Connects cost."""
    return _call(account, "get_job", locals(), lambda: ADAPTER.get_job(account, job_id))


@mcp.tool(annotations=READ, structured_output=True)
def get_client_history(account: str = Account, client_id: str = Field(min_length=1, max_length=64)) -> ClientHistory:
    """Client's marketplace history: payment verification, jobs posted, hires, spend, rating given."""
    return _call(account, "get_client_history", locals(), lambda: ADAPTER.get_client(account, client_id))


@mcp.tool(annotations=READ)
def get_connects_balance(account: str = Account) -> dict:
    """Current Connects balance."""
    return _call(account, "get_connects_balance", locals(), lambda: ADAPTER.connects(account))


@mcp.tool(annotations=READ, structured_output=True)
def get_connects_cost(account: str = Account, job_id: str = Field(min_length=1, max_length=64)) -> ConnectsCost:
    """Connects needed to bid on a job under the platform policy in force right now."""
    def run():
        job = ADAPTER.get_job(account, job_id)
        pol = ADAPTER.policy(account)
        return {"job_id": job_id, "connects": job["connects_required"], "policy_version": pol["version"],
                "policy_summary": pol["summary"]}
    return _call(account, "get_connects_cost", locals(), run)


@mcp.tool(annotations=READ)
def get_policy(account: str = Account) -> dict:
    """Platform policy currently in force (version, summary and machine-readable switches)."""
    return _call(account, "get_policy", locals(), lambda: ADAPTER.policy(account))


@mcp.tool(annotations=READ, structured_output=True)
def market_stats(account: str = Account, category: str = Field(min_length=1, max_length=40)) -> MarketStats:
    """Awarded-price percentiles for a job category, from historical jobs."""
    return _call(account, "market_stats", locals(), lambda: ADAPTER.market_stats(account, category))


@mcp.tool(annotations=READ)
def list_messages(account: str = Account) -> dict:
    """Client message threads for this account."""
    return _call(account, "list_messages", locals(), lambda: ADAPTER.list_messages(account))


@mcp.tool(annotations=READ)
def list_proposals(account: str = Account) -> dict:
    """Submitted proposals and their current status (submitted, viewed, replied, interview, hired)."""
    return _call(account, "list_proposals", locals(), lambda: ADAPTER.list_proposals(account))


# ------------------------------------------------------------------ write tools
def _preview(account: str, body: dict) -> ProposalPreview:
    job = ADAPTER.get_job(account, body["job_id"])
    try:
        bal = ADAPTER.connects(account)["balance"]
    except MarketplaceError:
        bal = None
    cost = job["connects_required"]
    return ProposalPreview(job_id=body["job_id"], cover_letter=body["cover_letter"], bid_amount=body["bid_amount"],
                           answers=body["answers"], connects_cost=cost, balance_after=None if bal is None else bal - cost)


@mcp.tool(annotations=DRAFT, structured_output=True)
def create_proposal_draft(account: str = Account, job_id: str = Field(min_length=1, max_length=64),
                          cover_letter: str = Field(min_length=40, max_length=5000),
                          bid_amount: float = Field(gt=0, le=100000),
                          answers: list[str] = Field(default_factory=list, max_length=10)) -> DraftOut:
    """Store a proposal draft inside GigBid (nothing is sent). Same content -> same draft id."""
    body = {"job_id": job_id, "cover_letter": cover_letter, "bid_amount": float(bid_amount), "answers": list(answers)}
    draft_id = "d" + hashlib.sha256(f"{account}|{body}".encode()).hexdigest()[:12]

    def run():
        LEDGER.save_draft(draft_id, account, body)
        return {"draft_id": draft_id, "preview": _preview(account, body).model_dump()}
    return _call(account, "create_proposal_draft", {"account": account, "job_id": job_id}, run)


@mcp.tool(annotations=SEND, structured_output=True)
def submit_proposal(account: str = Account, draft_id: str = Field(min_length=5, max_length=40),
                    idempotency_key: str = Field(min_length=8, max_length=128),
                    approval_grant: str | None = Field(None, max_length=2000),
                    dry_run: bool = True) -> SubmitOut:
    """Submit an approved draft and spend Connects. dry_run=true (default) returns exactly what would be sent and
    what it costs. A real submit needs the approval_grant from the GigBid UI; a retried call with the same
    idempotency_key never submits twice."""
    def run():
        body = LEDGER.get_draft(draft_id, account)
        if body is None:
            raise MarketplaceError("not_found", f"draft {draft_id} not found")
        preview = _preview(account, body)
        if dry_run:
            return {"status": "dry_run", "preview": preview.model_dump()}
        prior = LEDGER.idem_get(account, idempotency_key)
        if prior:
            return {**prior, "idempotent_replay": True}
        if not approval_grant:
            raise GrantError("approval_grant required for a real submit")
        claims = LEDGER.check(approval_grant, account, "submit_proposal", body)
        pol = ADAPTER.policy(account)
        if pol.get("requires_all_screening_answers") and config()["policy"]["require_all_screening_answers"]:
            job = ADAPTER.get_job(account, body["job_id"])
            if len([a for a in body["answers"] if a.strip()]) < len(job["screening_questions"]):
                raise MarketplaceError("rejected", "policy: every screening question must be answered")
        res = ADAPTER.submit_proposal(account, {**body, "idempotency_key": idempotency_key})
        LEDGER.consume(claims["jti"])
        out = {"status": "submitted", "preview": preview.model_dump(), "proposal_id": res["proposal_id"],
               "connects_spent": res["connects_spent"]}
        LEDGER.idem_put(account, idempotency_key, out)
        return out
    args = {"account": account, "draft_id": draft_id, "idempotency_key": idempotency_key, "dry_run": dry_run}
    return _call(account, "submit_proposal", args, run)


@mcp.tool(annotations=SEND, structured_output=True)
def send_message(account: str = Account, thread_id: str = Field(min_length=1, max_length=64),
                 text: str = Field(min_length=1, max_length=3000),
                 idempotency_key: str = Field(min_length=8, max_length=128),
                 approval_grant: str | None = Field(None, max_length=2000), dry_run: bool = True) -> MessageOut:
    """Send a message in a client thread. dry_run=true returns the exact text; a real send needs an approval grant."""
    def run():
        if dry_run:
            return {"status": "dry_run", "thread_id": thread_id, "text": text}
        prior = LEDGER.idem_get(account, idempotency_key)
        if prior:
            return {**prior, "idempotent_replay": True}
        if not approval_grant:
            raise GrantError("approval_grant required for a real send")
        claims = LEDGER.check(approval_grant, account, "send_message", {"thread_id": thread_id, "text": text})
        ADAPTER.send_message(account, {"thread_id": thread_id, "text": text, "idempotency_key": idempotency_key})
        LEDGER.consume(claims["jti"])
        out = {"status": "sent", "thread_id": thread_id, "text": text}
        LEDGER.idem_put(account, idempotency_key, out)
        return out
    args = {"account": account, "thread_id": thread_id, "idempotency_key": idempotency_key, "dry_run": dry_run}
    return _call(account, "send_message", args, run)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    try:
        ok = ADAPTER.request("health", "GET", "/health")
        return JSONResponse({"ok": True, "gigsim": ok})
    except MarketplaceError as e:
        return JSONResponse({"ok": False, "gigsim": str(e)}, status_code=503)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.getenv("PORT", "8201")))
    args = ap.parse_args()
    import uvicorn

    from mcp_servers.common import http_auth_app
    uvicorn.run(http_auth_app(mcp.streamable_http_app(), "marketplace"), host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
