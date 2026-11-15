"""Approvals: the human gate. Approving mints a one-time grant bound to the exact text and resumes the graph."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from apps.api import services
from apps.api.auth.security import CurrentUser
from apps.api.db import Approval, session
from apps.api.routers.proposals import regenerate_sentence
from apps.api.schemas.models import Accepted, ApprovalOut, DecisionIn
from mcp_servers.marketplace.approvals import mint

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


def out(a: Approval) -> ApprovalOut:
    return ApprovalOut(id=a.id, kind=a.kind, subject=a.subject, status=a.status, payload=a.payload, created=a.created)


@router.get("", response_model=list[ApprovalOut])
def pending(kind: str | None = None, user: str = CurrentUser) -> list[ApprovalOut]:
    with session() as s:
        q = select(Approval).where(Approval.user_id == user, Approval.status == "pending")
        rows = list(s.scalars(q))
    return [out(a) for a in rows if not kind or a.kind == kind]


@router.get("/{approval_id}", response_model=ApprovalOut)
def get(approval_id: str, user: str = CurrentUser) -> ApprovalOut:
    with session() as s:
        a = s.get(Approval, approval_id)
        if not a or a.user_id != user:
            raise HTTPException(404, "approval not found")
        return out(a)


@router.post("/{approval_id}/decision", response_model=Accepted)
def decide(approval_id: str, body: DecisionIn, user: str = CurrentUser) -> Accepted:
    with session() as s:
        a = s.get(Approval, approval_id)
        if not a or a.user_id != user:
            raise HTTPException(404, "approval not found")
        if a.status != "pending":
            raise HTTPException(409, f"already {a.status}")   # double clicks never resume twice
        a.status, a.decision = "processing", body.model_dump()
        payload, kind, subject = a.payload, a.kind, a.subject
    value: dict = {"action": body.action, "user": user}
    if body.action == "approve":
        if kind == "proposal":
            p = payload["preview"]
            value["grant"] = mint(user, "submit_proposal", {"job_id": p["job_id"], "cover_letter": p["cover_letter"],
                                                            "bid_amount": p["bid_amount"], "answers": p["answers"]},
                                  approval_id)
        else:
            value["grant"] = mint(user, "send_message", {"thread_id": subject, "text": payload["reply"]["text"]},
                                  approval_id)
            value["slot"] = body.slot
    elif body.action == "edit":
        if not body.text:
            raise HTTPException(422, "edit needs text")
        value["text"], value["answers"] = body.text, body.answers
    elif body.action == "regenerate":
        if kind != "proposal" or body.paragraph is None:
            raise HTTPException(422, "regenerate needs a paragraph index on a proposal")
        value["text"] = regenerate_sentence(payload, body.paragraph)
    else:
        value["reason"] = body.reason or ""
        services.note_rejection(user, subject, body.reason or "")
    services.dispatch("resume", user_id=user, kind="bid" if kind == "proposal" else "conversation", ident=subject,
                      value=value, approval_id=approval_id)
    return Accepted(detail=f"{body.action} recorded")
