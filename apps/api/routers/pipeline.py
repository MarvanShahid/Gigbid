"""Pipeline board (kanban)."""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from agent.mcp_client import ToolCallError, ToolUnavailable
from apps.api import services
from apps.api.auth.security import CurrentUser
from apps.api.db import PipelineCard, session
from apps.api.schemas.models import PipelineOut, StageIn

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])
STAGES = ["drafted", "submitted", "viewed", "replied", "interview", "hired", "lost"]


@router.get("", response_model=PipelineOut)
def board(user: str = CurrentUser) -> PipelineOut:
    with session() as s:
        cards = [{"id": c.id, "job_id": c.job_id, "proposal_id": c.proposal_id, "title": c.title, "category": c.category,
                  "stage": c.stage, "bid": c.bid, "connects": c.connects, "updated": c.updated}
                 for c in s.scalars(select(PipelineCard).where(PipelineCard.user_id == user))]
    return PipelineOut(stages=STAGES, cards=sorted(cards, key=lambda c: -c["updated"]))


@router.post("/sync")
async def sync(user: str = CurrentUser) -> dict:
    try:
        res = await services.sync_pipeline(user)
    except (ToolUnavailable, ToolCallError) as e:
        raise HTTPException(503, f"marketplace unavailable: {e}") from e
    for tid in res["threads_needing_reply"]:
        services.dispatch("run_conversation", user_id=user, thread_id=tid)
    return res


@router.patch("/{card_id}")
def move(card_id: int, body: StageIn, user: str = CurrentUser) -> dict:
    with session() as s:
        c = s.get(PipelineCard, card_id)
        if not c or c.user_id != user:
            raise HTTPException(404, "card not found")
        c.stage, c.updated = body.stage, time.time()
    if body.stage == "lost" and c.proposal_id:
        from agent.memory.promotion_rules import record_outcome
        record_outcome(user, c.proposal_id, c.category, c.features or {}, "lost")
    return {"ok": True}
