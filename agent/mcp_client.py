"""MCP client setup: the only way agents reach tools (A6, R2).

* Per-agent allowlists from config (`mcp.allowlists`), enforced on every call.
* Timeouts and bounded retries with exponential backoff for transient errors.
* Degraded mode: when a server stays unreachable, it is marked down in agent.health,
  the caller gets ToolUnavailable, and the API/UI show "marketplace unavailable".

Transports
  MCP_MODE=inmemory  servers run in-process (tests, local single-process dev)
  MCP_MODE=http      streamable HTTP via langchain-mcp-adapters' MultiServerMCPClient (docker compose)
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from agent import health
from agent.observability import get_trace_id, span
from agent.settings import config

TOOL_SERVER = {
    # portfolio
    "search_evidence": "portfolio", "retrieve_for_job": "portfolio", "get_case_study": "portfolio",
    "list_skills": "portfolio",
    # marketplace
    "search_jobs": "marketplace", "get_job": "marketplace", "get_client_history": "marketplace",
    "get_connects_balance": "marketplace", "get_connects_cost": "marketplace", "get_policy": "marketplace",
    "market_stats": "marketplace", "list_messages": "marketplace", "list_proposals": "marketplace",
    "create_proposal_draft": "marketplace", "submit_proposal": "marketplace", "send_message": "marketplace",
    # workspace
    "free_slots": "workspace", "create_interview_hold": "workspace", "create_email_draft": "workspace",
}
TRANSIENT = ("[unavailable]", "[rate_limited]")


class ToolUnavailable(Exception):
    def __init__(self, server: str, message: str) -> None:
        super().__init__(f"{server} unavailable: {message}")
        self.server = server


class ToolCallError(Exception):
    """The tool ran and refused (bad input, rejected by marketplace, approval missing)."""


class ToolNotAllowed(Exception):
    pass


def _inmemory_server(name: str):
    if name == "portfolio":
        from mcp_servers.portfolio.server import mcp
    elif name == "marketplace":
        from mcp_servers.marketplace.server import mcp
    elif name == "workspace":
        from mcp_servers.workspace.server import mcp
    else:
        raise KeyError(name)
    return mcp


def http_connections() -> dict[str, dict]:
    tok = os.getenv("MCP_CLIENT_TOKEN", "gigbid-internal-dev-token")
    hdr = {"Authorization": f"Bearer {tok}"}
    return {
        "portfolio": {"transport": "streamable_http", "url": os.getenv("PORTFOLIO_MCP_URL", "http://localhost:8202/mcp"),
                      "headers": hdr},
        "marketplace": {"transport": "streamable_http", "url": config()["marketplace"]["gigsim_mcp_url"], "headers": hdr},
        "workspace": {"transport": "streamable_http", "url": os.getenv("WORKSPACE_MCP_URL", "http://localhost:8203/mcp"),
                      "headers": hdr},
    }


def _unwrap(result) -> Any:
    if result.isError:
        text = " ".join(getattr(c, "text", "") for c in result.content)
        raise ToolCallError(text)
    sc = result.structuredContent
    if sc is not None:
        return sc["result"] if set(sc) == {"result"} else sc
    texts = [getattr(c, "text", "") for c in result.content]
    if len(texts) == 1:
        try:
            return json.loads(texts[0])
        except (json.JSONDecodeError, TypeError):
            return texts[0]
    out = []
    for t in texts:
        try:
            out.append(json.loads(t))
        except (json.JSONDecodeError, TypeError):
            out.append(t)
    return out


class Gateway:
    def __init__(self, mode: str | None = None, extra_connections: dict[str, dict] | None = None,
                 tool_server: dict[str, str] | None = None) -> None:
        self.mode = mode or os.getenv("MCP_MODE", "inmemory")
        cfg = config()["mcp"]
        self.timeout = float(cfg["timeout_seconds"])
        self.retries = int(cfg["retries"])
        self.backoff = float(cfg["backoff_seconds"])
        self.allow = {k: set(v) for k, v in cfg["allowlists"].items()}
        self.extra = extra_connections or {}
        self.tool_server = {**TOOL_SERVER, **(tool_server or {})}
        self.calls: list[dict] = []   # execution trace for this gateway instance (audit/debug)
        self.down: set[str] = set()   # test hook: simulate a killed server

    def allowed(self, agent: str, tool: str) -> bool:
        return agent in ("system", "eval") or tool in self.allow.get(agent, set())

    async def _raw_call(self, server: str, tool: str, args: dict):
        if server in self.down:
            raise ConnectionError(f"{server} is down")
        if self.mode == "inmemory" and server not in self.extra:
            from mcp.shared.memory import create_connected_server_and_client_session
            async with create_connected_server_and_client_session(_inmemory_server(server)) as s:
                return await s.call_tool(tool, args)
        from langchain_mcp_adapters.client import MultiServerMCPClient
        conns = {**http_connections(), **self.extra}
        conn = dict(conns[server])
        conn["headers"] = {**(conn.get("headers") or {}), "x-trace-id": get_trace_id()}
        client = MultiServerMCPClient({server: conn})
        async with client.session(server) as s:
            return await s.call_tool(tool, args)

    async def call(self, agent: str, tool: str, args: dict) -> Any:
        if not self.allowed(agent, tool):
            raise ToolNotAllowed(f"agent '{agent}' may not call '{tool}'")
        server = self.tool_server.get(tool)
        if server is None:
            raise ToolNotAllowed(f"unknown tool {tool}")
        delay, last = self.backoff, None
        for attempt in range(self.retries + 1):
            with span(f"mcp.{server}.{tool}", agent=agent, tool=tool, attempt=attempt, args=json.dumps(args)[:500]) as sp:
                try:
                    res = await asyncio.wait_for(self._raw_call(server, tool, args), self.timeout)
                    out = _unwrap(res)
                    health.mark(server, True)
                    self.calls.append({"agent": agent, "tool": tool, "args": args, "ok": True})
                    sp.set_attribute("ok", True)
                    return out
                except ToolCallError as e:
                    msg = str(e)
                    if not any(t in msg for t in TRANSIENT):
                        self.calls.append({"agent": agent, "tool": tool, "args": args, "ok": False, "error": msg})
                        sp.set_attribute("ok", False)
                        raise
                    last = msg
                except (ConnectionError, OSError, asyncio.TimeoutError, TimeoutError) as e:
                    last = f"{type(e).__name__}: {e}"
                except Exception as e:  # noqa: BLE001  transport errors from httpx/anyio/ExceptionGroup
                    last = f"{type(e).__name__}: {e}"
                sp.set_attribute("ok", False)
                sp.set_attribute("error", str(last)[:300])
            if attempt < self.retries:
                await asyncio.sleep(delay)
                delay *= 2
        health.mark(server, False, str(last))
        self.calls.append({"agent": agent, "tool": tool, "args": args, "ok": False, "error": str(last)})
        raise ToolUnavailable(server, str(last))

    async def list_tools(self, server: str) -> list:
        if self.mode == "inmemory" and server not in self.extra:
            from mcp.shared.memory import create_connected_server_and_client_session
            async with create_connected_server_and_client_session(_inmemory_server(server)) as s:
                return (await s.list_tools()).tools
        from langchain_mcp_adapters.client import MultiServerMCPClient
        client = MultiServerMCPClient({server: {**http_connections(), **self.extra}[server]})
        async with client.session(server) as s:
            return (await s.list_tools()).tools

    async def langchain_tools(self, agent: str, account: str, owner: str, names: list[str] | None = None):
        """LangChain tools (for the ReAct / supervisor baselines), filtered by the agent's allowlist.
        `account`/`owner` are bound so a model can never act for another tenant."""
        from langchain_core.tools import StructuredTool
        tools = []
        wanted = set(names) if names else None
        for server in ("portfolio", "marketplace", "workspace"):
            for t in await self.list_tools(server):
                if not self.allowed(agent, t.name) or (wanted and t.name not in wanted):
                    continue
                schema = json.loads(json.dumps(t.inputSchema))
                props = schema.get("properties", {})
                for bound in ("account", "owner"):
                    props.pop(bound, None)
                    if bound in schema.get("required", []):
                        schema["required"].remove(bound)
                tools.append(StructuredTool.from_function(
                    coroutine=self._bound(agent, t.name, account, owner, t.inputSchema), name=t.name,
                    description=t.description or t.name, args_schema=schema))
        return tools

    def _bound(self, agent, tool, account, owner, schema):
        props = schema.get("properties", {})

        async def run(**kwargs):
            if "account" in props:
                kwargs["account"] = account
            if "owner" in props:
                kwargs["owner"] = owner
            try:
                return json.dumps(await self.call(agent, tool, kwargs), default=str)[:6000]
            except (ToolCallError, ToolUnavailable, ToolNotAllowed) as e:
                return f"ERROR: {e}"
        return run


_GATEWAY: Gateway | None = None


def gateway() -> Gateway:
    global _GATEWAY
    if _GATEWAY is None:
        _GATEWAY = Gateway()
    return _GATEWAY


def set_gateway(g: Gateway | None) -> None:
    global _GATEWAY
    _GATEWAY = g
