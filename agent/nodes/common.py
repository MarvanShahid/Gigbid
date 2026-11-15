"""Node plumbing: budgets (C4), per-node timeouts and timing, usage accounting."""
from __future__ import annotations

import asyncio
import functools
import time
from typing import Any, Awaitable, Callable

from langgraph.types import Command

from agent.observability import set_trace_id, span
from agent.settings import config


class BudgetExceeded(Exception):
    pass


NODE_TIMEOUT_S = {"writer": 90, "critic": 60, "matcher": 60, "liaison": 60}


def usage_update(usage: dict | None) -> dict:
    if not usage:
        return {}
    return {"tokens": int(usage.get("tokens", 0)), "cost_usd": float(usage.get("cost_usd", 0.0))}


def merge_usage(*usages: dict | None) -> dict:
    out = {"tokens": 0, "cost_usd": 0.0}
    for u in usages:
        if u:
            out["tokens"] += int(u.get("tokens", 0))
            out["cost_usd"] += float(u.get("cost_usd", 0.0))
    return out


def halted(state: dict) -> bool:
    return state.get("status") == "needs_attention"


def node(name: str, timeout: float | None = None):
    """Wrap a graph node: check step/token budgets first, time it, trace it, enforce a timeout.
    If a budget is exceeded the thread is moved to the visible 'needs_attention' state."""
    def deco(fn: Callable[[dict], Awaitable[dict]]):
        @functools.wraps(fn)
        async def wrapped(state: dict) -> Any:
            if state.get("trace_id"):
                set_trace_id(state["trace_id"])
            if halted(state):
                return {}   # thread is parked in "needs attention": remaining nodes do nothing
            b = config()["budgets"]
            if state.get("steps", 0) >= b["max_steps_per_thread"] or state.get("tokens", 0) >= b["max_tokens_per_thread"]:
                return {"status": "needs_attention",
                        "error": f"budget exceeded before {name}: steps={state.get('steps', 0)} tokens={state.get('tokens', 0)}"}
            t0 = time.perf_counter()
            with span(f"node.{name}", node=name, job_id=state.get("job_id") or state.get("thread_id")):
                if timeout == -1:   # human-in-the-loop nodes wait as long as the human needs
                    out = await fn(state)
                else:
                    out = await asyncio.wait_for(fn(state), timeout or NODE_TIMEOUT_S.get(name, 45))
            if isinstance(out, Command):
                upd = dict(out.update or {})
                upd["steps"] = upd.get("steps", 0) + 1
                upd["node_latency"] = {name: round(time.perf_counter() - t0, 3)}
                return Command(goto=out.goto, update=upd)
            out = dict(out or {})
            out["steps"] = out.get("steps", 0) + 1
            out["node_latency"] = {name: round(time.perf_counter() - t0, 3)}
            return out
        return wrapped
    return deco
