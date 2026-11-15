"""Typed graph state and reducers (C2).

Three things are kept apart:
* State (this file): what one job / conversation needs right now. Hand-off objects
  are stored as dicts (model_dump) so checkpoints stay JSON-friendly.
* Execution trace: every tool call, argument, result and model call goes to the
  OpenTelemetry trace (agent/observability.py) and the MCP audit log, keyed by
  `trace_id`. It is NOT in state.
* Long-term memory: only promoted knowledge, in a LangGraph store
  (agent/memory/), written by explicit promotion rules.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


def merge_dicts(a: dict | None, b: dict | None) -> dict:
    """Reducer for fields the parallel branches write concurrently."""
    out = dict(a or {})
    out.update(b or {})
    return out


def keep_last_status(a: str | None, b: str | None) -> str | None:
    """'needs_attention' and 'dead_letter' are sticky; otherwise the latest wins."""
    if a in ("needs_attention", "dead_letter") and b not in ("needs_attention", "dead_letter"):
        return a
    return b if b is not None else a


class UserCtx(TypedDict, total=False):
    account: str          # tenant id used on every MCP call
    owner: str            # portfolio owner (persona folder or user id)
    hourly_floor: float
    hourly_rate: float
    autonomy: str         # suggest | auto_skip
    categories: list[str]
    weekly_connects_budget: int
    connects_spent_week: int


class BidState(TypedDict, total=False):
    job_id: str
    trace_id: str
    user: UserCtx
    job: dict
    analyses: Annotated[dict[str, Any], merge_dicts]   # spec, risk, fit, brief  (parallel writers)
    decision: dict
    price: dict
    evidence: list[dict]
    draft: dict
    verification: dict
    critiques: Annotated[list[dict], operator.add]
    critic_round: int
    compliance: dict
    preview: dict
    approval: dict
    approvals_log: Annotated[list[dict], operator.add]
    submission: dict
    status: Annotated[str | None, keep_last_status]
    error: str | None
    steps: Annotated[int, operator.add]
    tokens: Annotated[int, operator.add]
    cost_usd: Annotated[float, operator.add]
    node_latency: Annotated[dict[str, float], merge_dicts]


class ConvState(TypedDict, total=False):
    thread_id: str
    trace_id: str
    user: UserCtx
    thread: dict
    last_client_message: str
    injection_detected: bool
    intent: dict
    slots: list[dict]
    reply: dict
    compliance: dict
    approval: dict
    approvals_log: Annotated[list[dict], operator.add]
    sent: dict
    status: Annotated[str | None, keep_last_status]
    steps: Annotated[int, operator.add]
    tokens: Annotated[int, operator.add]
    cost_usd: Annotated[float, operator.add]
