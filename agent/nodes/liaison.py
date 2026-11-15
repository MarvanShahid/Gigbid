"""Client Liaison nodes for the conversation graph."""
from __future__ import annotations

import hashlib
import re

from langgraph.types import Command, interrupt

from agent import llm
from agent.guardrails import delimit, detect_injection, neutralise
from agent.handoffs import Intent, ReplyDraft
from agent.marketplace_port import get_port
from agent.mcp_client import ToolCallError, ToolUnavailable, gateway
from agent.memory.promotion_rules import apply_style, promote_style, style_rules
from agent.nodes.analysis import RISK_RULES
from agent.nodes.common import node, usage_update
from agent.nodes.proposal import check_text
from agent.prompts import prompt


@node("read_thread")
async def read_thread(state: dict) -> dict:
    port = get_port(state["user"]["account"])
    threads = await port.list_messages("liaison")
    t = next((x for x in threads if x["id"] == state["thread_id"]), None)
    if t is None:
        return {"status": "dead_letter", "thread": {}, "last_client_message": ""}
    last = next((m["text"] for m in reversed(t["messages"]) if m["from"] == "client"), "")
    return {"thread": t, "last_client_message": last, "injection_detected": bool(detect_injection(last)),
            "status": "reading"}


def classify_rules(msg: str) -> Intent:
    for kind, pat, w in RISK_RULES:
        if re.search(pat, msg) and w >= 0.7:
            return Intent(intent="scam_signal", confidence=w, notes=f"{kind}: {re.search(pat, msg).group(0)}")
    low = msg.lower()
    if re.search(r"\b(call|meeting|interview|zoom|chat live|time slots?|times?)\b", low):
        return Intent(intent="interview_request", confidence=0.8)
    if re.search(r"\b(price|rate|budget|discount|cheaper|lower|cost|\$)\b", low):
        return Intent(intent="negotiation", confidence=0.7)
    if "?" in msg:
        return Intent(intent="question", confidence=0.6)
    return Intent(intent="other", confidence=0.4)


@node("intent")
async def classify(state: dict) -> dict:
    msg = state["last_client_message"]
    usage = None
    rule = classify_rules(msg)
    if rule.intent == "scam_signal":
        return {"intent": rule.model_dump()}
    try:
        it, usage = llm.call("intent", "Return an Intent.",
                             prompt("intent", message=delimit("client_message", neutralise(msg)[0])), Intent)
    except Exception:  # noqa: BLE001  (NoModel or model failure)
        it = rule
    return {"intent": it.model_dump(), **usage_update(usage)}


def route_intent(state: dict) -> str:
    return "slots" if state["intent"]["intent"] == "interview_request" else "draft_reply"


@node("slots")
async def slots(state: dict) -> dict:
    try:
        s = await gateway().call("liaison", "free_slots", {"account": state["user"]["account"], "days": 5,
                                                          "duration_minutes": 30, "max_slots": 3})
    except (ToolUnavailable, ToolCallError):
        s = []
    return {"slots": s}


def reply_rules(state: dict) -> ReplyDraft:
    intent = state["intent"]["intent"]
    if intent == "scam_signal":
        text = ("Thanks for the message. I keep all communication and payments on this platform, so I can't move "
                "this conversation elsewhere or pay any fee. Happy to continue here if that works for you.")
    elif intent == "interview_request" and state.get("slots"):
        labels = "; ".join(s["label"] for s in state["slots"])
        text = f"Thanks, a short call would be great. I am free at these times: {labels}. Let me know which suits you."
    elif intent == "negotiation":
        text = ("Thanks for being upfront about the budget. I would rather keep the rate and reduce the first "
                "milestone to the core features, so you see results before committing to the rest. Shall I outline that scope?")
    else:
        text = ("Thanks for the reply. My first milestone would be a working version of the core feature within two "
                "weeks, with a short demo so you can give feedback early. Happy to walk through it on a call if that helps.")
    return ReplyDraft(text=text, slots=state.get("slots") or [], source="rules")


@node("draft_reply")
async def draft_reply(state: dict) -> dict:
    user = state["user"]
    usage = None
    try:
        if state["intent"]["intent"] == "scam_signal":
            raise llm.NoModel("fixed safe reply")
        text, usage = llm.call("liaison", "Write the reply text only.", prompt(
            "liaison", intent=state["intent"]["intent"], slots=[s["label"] for s in state.get("slots") or []],
            floor=user.get("hourly_floor", 25), evidence="(see proposal)", style=style_rules(user["account"]) or "none",
            thread=delimit("thread", "\n".join(f"{m['from']}: {neutralise(m['text'])[0]}"
                                               for m in state["thread"]["messages"][-6:]))))
        rep = ReplyDraft(text=str(text).strip(), slots=state.get("slots") or [], source="llm")
    except llm.NoModel:
        rep = reply_rules(state)
    rep.text = apply_style(rep.text, user["account"])
    return {"reply": rep.model_dump(), **usage_update(usage)}


@node("reply_compliance")
async def reply_compliance(state: dict) -> dict:
    text, viols, blocked = check_text(state["reply"]["text"])
    status = "blocked" if blocked or not text else ("fixed" if viols else "pass")
    return {"compliance": {"status": status, "violations": [v.model_dump() for v in viols], "cleaned_text": text},
            "reply": {**state["reply"], "text": text}, "status": "awaiting_approval" if status != "blocked" else "blocked"}


def route_reply(state: dict) -> str:
    return "end" if state["compliance"]["status"] == "blocked" else "approve_reply"


@node("approve_reply", timeout=-1)
async def approve_reply(state: dict) -> Command:
    decision = interrupt({"kind": "message", "thread_id": state["thread_id"], "thread": state["thread"],
                          "intent": state["intent"], "reply": state["reply"], "slots": state.get("slots") or [],
                          "compliance": state["compliance"], "injection_detected": state.get("injection_detected"),
                          "preview": {"thread_id": state["thread_id"], "text": state["reply"]["text"]}})
    action = decision.get("action")
    if action == "approve":
        return Command(goto="send", update={"approval": {"action": "approve", "grant": decision["grant"],
                                                          "slot": decision.get("slot")},
                                             "approvals_log": [{"action": "approve"}], "status": "approved"})
    if action == "edit":
        promote_style(state["user"]["account"], state["thread_id"], state["reply"]["text"], decision["text"])
        return Command(goto="reply_compliance", update={"reply": {**state["reply"], "text": decision["text"]},
                                                        "approvals_log": [{"action": "edit"}]})
    return Command(goto="end", update={"approval": {"action": "reject", "reason": decision.get("reason", "")},
                                       "approvals_log": [{"action": "reject", "reason": decision.get("reason")}],
                                       "status": "rejected"})


def msg_key(state: dict) -> str:
    return hashlib.sha256(f"{state['user']['account']}|{state['thread_id']}|{state['reply']['text']}".encode()).hexdigest()[:32]


@node("send")
async def send(state: dict) -> dict:
    user, ap = state["user"], state["approval"]
    port = get_port(user["account"])
    res = await port.send_message("liaison", state["thread_id"], state["reply"]["text"], msg_key(state), ap["grant"], False)
    if ap.get("slot"):
        try:
            await gateway().call("liaison", "create_interview_hold", {
                "account": user["account"], "start": ap["slot"]["start"], "duration_minutes": 30,
                "title": f"Client call ({state['thread_id']})", "idempotency_key": msg_key(state) + "h"})
        except (ToolUnavailable, ToolCallError):
            pass
    return {"sent": res, "status": "sent"}


@node("end")
async def end(state: dict) -> dict:
    return {}
