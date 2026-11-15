"""The single marketplace interface (R1). The graph only ever sees MarketplacePort.

GigSimPort  -> GigBid's own Marketplace MCP server (which wraps GigSim)
UpworkPort  -> Upwork's official MCP server (OAuth 2.1), tool names mapped in
               mcp_servers/marketplace/adapters/upwork_tools.yaml

Switch with `marketplace.mode` in agent/config.yaml. Nothing in agent/graphs or
agent/nodes changes between the two."""
from __future__ import annotations

import uuid
from typing import Any, Protocol

from agent.mcp_client import Gateway, gateway
from agent.settings import config


class MarketplacePort(Protocol):
    name: str
    supports_submit: bool

    async def search_jobs(self, agent: str, query: str = "", category: str | None = None, limit: int = 20) -> list[dict]: ...
    async def get_job(self, agent: str, job_id: str) -> dict: ...
    async def get_client_history(self, agent: str, client_id: str) -> dict: ...
    async def connects_balance(self, agent: str) -> int: ...
    async def connects_cost(self, agent: str, job_id: str) -> dict: ...
    async def market_stats(self, agent: str, category: str) -> dict | None: ...
    async def list_messages(self, agent: str) -> list[dict]: ...
    async def create_draft(self, agent: str, job_id: str, cover_letter: str, bid_amount: float, answers: list[str]) -> dict: ...
    async def submit(self, agent: str, draft_id: str, idempotency_key: str, grant: str | None, dry_run: bool) -> dict: ...
    async def send_message(self, agent: str, thread_id: str, text: str, idempotency_key: str, grant: str | None,
                           dry_run: bool) -> dict: ...


class GigSimPort:
    name = "gigsim"
    supports_submit = True

    def __init__(self, account: str, gw: Gateway | None = None) -> None:
        self.account = account
        self.gw = gw or gateway()

    async def _c(self, agent: str, tool: str, **args) -> Any:
        return await self.gw.call(agent, tool, {"account": self.account, **args})

    async def search_jobs(self, agent, query="", category=None, limit=20):
        args = {"query": query, "limit": limit}
        if category:
            args["category"] = category
        return (await self._c(agent, "search_jobs", **args))["jobs"]

    async def get_job(self, agent, job_id):
        return await self._c(agent, "get_job", job_id=job_id)

    async def get_client_history(self, agent, client_id):
        return await self._c(agent, "get_client_history", client_id=client_id)

    async def connects_balance(self, agent):
        return int((await self._c(agent, "get_connects_balance"))["balance"])

    async def connects_cost(self, agent, job_id):
        return await self._c(agent, "get_connects_cost", job_id=job_id)

    async def market_stats(self, agent, category):
        return await self._c(agent, "market_stats", category=category)

    async def list_messages(self, agent):
        return (await self._c(agent, "list_messages"))["threads"]

    async def create_draft(self, agent, job_id, cover_letter, bid_amount, answers):
        return await self._c(agent, "create_proposal_draft", job_id=job_id, cover_letter=cover_letter,
                             bid_amount=bid_amount, answers=answers)

    async def submit(self, agent, draft_id, idempotency_key, grant, dry_run):
        return await self._c(agent, "submit_proposal", draft_id=draft_id, idempotency_key=idempotency_key,
                             approval_grant=grant, dry_run=dry_run)

    async def send_message(self, agent, thread_id, text, idempotency_key, grant, dry_run):
        return await self._c(agent, "send_message", thread_id=thread_id, text=text, idempotency_key=idempotency_key,
                             approval_grant=grant, dry_run=dry_run)


class UpworkPort:
    """Upwork live mode. Writes create drafts the user confirms on Upwork; there is no submit."""

    name = "upwork_live"
    supports_submit = False

    def __init__(self, account: str, connection: dict) -> None:
        from mcp_servers.marketplace.adapters.upwork_live import to_job, tool_map
        self.account, self.map, self.to_job = account, tool_map(), to_job
        names = {v["tool"]: "upwork" for v in self.map.values()}
        self.gw = Gateway(mode="http", extra_connections={"upwork": connection}, tool_server=names)
        # Upwork tools are allowed for the same agents that may use the GigSim equivalents
        for agent, allowed in list(self.gw.allow.items()):
            self.gw.allow[agent] = allowed | {self.map[t]["tool"] for t in allowed if t in self.map}

    async def _c(self, agent, method, **args):
        m = self.map[method]
        mapped = {m["args"][k]: v for k, v in args.items() if k in m["args"]}
        # the allowlist is checked against GigBid's tool name, then the Upwork name is called
        if not self.gw.allowed(agent, method):
            from agent.mcp_client import ToolNotAllowed
            raise ToolNotAllowed(f"agent '{agent}' may not call '{method}'")
        return await self.gw.call("system", m["tool"], mapped)

    async def search_jobs(self, agent, query="", category=None, limit=20):
        raw = await self._c(agent, "search_jobs", query=query, limit=limit)
        items = raw.get("jobs", raw) if isinstance(raw, dict) else raw
        return [self.to_job(j) for j in items]

    async def get_job(self, agent, job_id):
        return self.to_job(await self._c(agent, "get_job", job_id=job_id))

    async def get_client_history(self, agent, client_id):
        return await self._c(agent, "get_client_history", client_id=client_id)

    async def connects_balance(self, agent):
        raw = await self._c(agent, "get_connects_balance")
        return int(raw.get("balance", 0) if isinstance(raw, dict) else raw)

    async def connects_cost(self, agent, job_id):
        job = await self.get_job(agent, job_id)
        return {"job_id": job_id, "connects": job["connects_required"], "policy_version": 0,
                "policy_summary": "Upwork live"}

    async def market_stats(self, agent, category):
        return None  # Upwork exposes no statistics; pricing falls back to GigBid's own history

    async def list_messages(self, agent):
        raw = await self._c(agent, "list_messages")
        return raw.get("threads", raw) if isinstance(raw, dict) else raw

    async def create_draft(self, agent, job_id, cover_letter, bid_amount, answers):
        raw = await self._c(agent, "create_proposal_draft", job_id=job_id, cover_letter=cover_letter,
                            bid_amount=bid_amount, answers=answers)
        return {"draft_id": str(raw.get("id", uuid.uuid4().hex)) if isinstance(raw, dict) else str(raw),
                "preview": {"job_id": job_id, "cover_letter": cover_letter, "bid_amount": bid_amount,
                            "answers": answers, "connects_cost": 0, "balance_after": None},
                "note": "Draft created on Upwork. Confirm it on upwork.com."}

    async def submit(self, agent, draft_id, idempotency_key, grant, dry_run):
        return {"status": "dry_run" if dry_run else "draft_on_upwork", "proposal_id": draft_id,
                "preview": {}, "note": "Upwork requires the user to confirm the draft on upwork.com"}

    async def send_message(self, agent, thread_id, text, idempotency_key, grant, dry_run):
        if dry_run:
            return {"status": "dry_run", "thread_id": thread_id, "text": text}
        await self._c(agent, "send_message", thread_id=thread_id, text=text)
        return {"status": "draft_on_upwork", "thread_id": thread_id, "text": text}


def get_port(account: str, gw: Gateway | None = None) -> MarketplacePort:
    mode = config()["marketplace"]["mode"]
    if mode == "gigsim":
        return GigSimPort(account, gw)
    if mode == "upwork_live":
        import os

        from apps.api.auth.token_store import TokenStore
        from mcp_servers.marketplace.adapters.upwork_live import connection
        return UpworkPort(account, connection(account, TokenStore(), os.getenv(
            "UPWORK_REDIRECT_URI", "http://localhost:8000/api/auth/upwork/callback")))
    raise ValueError(f"unknown marketplace mode {mode}")
