"""Client message threads; drafting replies runs the conversation graph."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from agent.marketplace_port import get_port
from agent.mcp_client import ToolCallError, ToolUnavailable
from apps.api import services
from apps.api.auth.security import CurrentUser
from apps.api.db import Approval, session
from apps.api.schemas.models import Accepted

router = APIRouter(prefix="/api/messages", tags=["messages"])


@router.get("")
async def threads(user: str = CurrentUser) -> dict:
    try:
        ts = await get_port(user).list_messages("liaison")
    except (ToolUnavailable, ToolCallError) as e:
        raise HTTPException(503, f"marketplace unavailable: {e}") from e
    with session() as s:
        pend = {a.subject: a.id for a in s.scalars(select(Approval).where(
            Approval.user_id == user, Approval.kind == "message", Approval.status == "pending"))}
    for t in ts:
        t["approval_id"] = pend.get(t["id"])
        t["needs_reply"] = bool(t["messages"]) and t["messages"][-1]["from"] == "client"
    return {"threads": ts}


@router.post("/{thread_id}/draft", response_model=Accepted)
def draft(thread_id: str, user: str = CurrentUser) -> Accepted:
    services.dispatch("run_conversation", user_id=user, thread_id=thread_id)
    return Accepted(detail="drafting a reply")
