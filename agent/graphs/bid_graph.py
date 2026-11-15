"""Bid graph: one thread per job.

  scout_in -> [analyst | risk | researcher | matcher]  (parallel, via Send)
           -> decide -(skip/watch)-> finish
                     -(bid)-> pricing -(not worth Connects)-> finish
                                      -> writer -> verifier -> critic -(<=2 revisions)-> writer
                                                                      -> compliance -(blocked)-> finish
                                                                                    -> preview -> approval (interrupt)
                                                                                                  -> submit | compliance (edit) | finish (reject)
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, Send

from agent.marketplace_port import get_port
from agent.mcp_client import ToolCallError, ToolNotAllowed, ToolUnavailable
from agent.nodes.analysis import analyst, matcher, researcher, risk
from agent.nodes.common import node
from agent.nodes.proposal import (
    approval,
    compliance,
    critic,
    decide,
    finish,
    needs_attention,
    preview,
    pricing,
    route_compliance,
    route_critic,
    route_decision,
    route_pricing,
    submit,
    verifier,
    writer,
)
from agent.state import BidState

PARALLEL = ["analyst", "risk", "researcher", "matcher"]
CHEAP_RETRY = RetryPolicy(max_attempts=3, initial_interval=0.5, backoff_factor=2.0,
                          retry_on=lambda e: not isinstance(e, (ToolUnavailable, ToolNotAllowed, ToolCallError, KeyError,
                                                                ValueError)))


@node("scout_in")
async def scout_in(state: dict) -> dict:
    """Scout hands a job in: make sure we have the full post (the queue may only hold an id)."""
    job = state.get("job")
    if not job or "description" not in job:
        job = await get_port(state["user"]["account"]).get_job("scout", state["job_id"])
    return {"job": job, "status": "analysing"}


def fan_out(state: dict) -> list[Send]:
    return [Send(name, state) for name in PARALLEL]


def build(checkpointer=None, store=None):
    g = StateGraph(BidState)
    g.add_node("scout_in", scout_in, retry_policy=CHEAP_RETRY)
    g.add_node("analyst", analyst, retry_policy=CHEAP_RETRY)
    g.add_node("risk", risk, retry_policy=CHEAP_RETRY)
    g.add_node("researcher", researcher, retry_policy=CHEAP_RETRY)
    g.add_node("matcher", matcher, retry_policy=CHEAP_RETRY)
    g.add_node("decide", decide)
    g.add_node("pricing", pricing, retry_policy=CHEAP_RETRY)
    g.add_node("writer", writer, retry_policy=RetryPolicy(max_attempts=2))
    g.add_node("verifier", verifier)
    g.add_node("critic", critic, retry_policy=RetryPolicy(max_attempts=2))
    g.add_node("compliance", compliance)
    g.add_node("preview", preview, retry_policy=CHEAP_RETRY)
    g.add_node("approval", approval, destinations=("submit", "compliance", "finish"))
    g.add_node("submit", submit)
    g.add_node("finish", finish)
    g.add_node("needs_attention", needs_attention)

    g.add_edge(START, "scout_in")
    g.add_conditional_edges("scout_in", fan_out, PARALLEL)
    for n in PARALLEL:
        g.add_edge(n, "decide")
    g.add_conditional_edges("decide", route_decision, {"pricing": "pricing", "finish": "finish"})
    g.add_conditional_edges("pricing", route_pricing, {"writer": "writer", "finish": "finish"})
    g.add_edge("writer", "verifier")
    g.add_edge("verifier", "critic")
    g.add_conditional_edges("critic", route_critic, {"writer": "writer", "compliance": "compliance"})
    g.add_conditional_edges("compliance", route_compliance, {"preview": "preview", "finish": "finish"})
    g.add_edge("preview", "approval")
    g.add_edge("submit", "finish")
    g.add_edge("finish", END)
    g.add_edge("needs_attention", END)
    return g.compile(checkpointer=checkpointer, store=store, name="bid_graph")
