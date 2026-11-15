"""Conversation graph: one thread per client conversation.

  read_thread -> intent -(interview)-> slots -> draft_reply -> reply_compliance -(blocked)-> end
                        -(other)------------> draft_reply                       -> approve_reply (interrupt)
                                                                                   -> send | reply_compliance (edit) | end
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from agent.nodes.liaison import (
    approve_reply,
    classify,
    draft_reply,
    end,
    read_thread,
    reply_compliance,
    route_intent,
    route_reply,
    send,
    slots,
)
from agent.state import ConvState


def build(checkpointer=None, store=None):
    g = StateGraph(ConvState)
    g.add_node("read_thread", read_thread, retry_policy=RetryPolicy(max_attempts=3))
    g.add_node("intent", classify, retry_policy=RetryPolicy(max_attempts=2))
    g.add_node("slots", slots)
    g.add_node("draft_reply", draft_reply, retry_policy=RetryPolicy(max_attempts=2))
    g.add_node("reply_compliance", reply_compliance)
    g.add_node("approve_reply", approve_reply, destinations=("send", "reply_compliance", "end"))
    g.add_node("send", send)
    g.add_node("end", end)
    g.add_edge(START, "read_thread")
    g.add_edge("read_thread", "intent")
    g.add_conditional_edges("intent", route_intent, {"slots": "slots", "draft_reply": "draft_reply"})
    g.add_edge("slots", "draft_reply")
    g.add_edge("draft_reply", "reply_compliance")
    g.add_conditional_edges("reply_compliance", route_reply, {"approve_reply": "approve_reply", "end": "end"})
    g.add_edge("send", "end")
    g.add_edge("end", END)
    return g.compile(checkpointer=checkpointer, store=store, name="conversation_graph")
