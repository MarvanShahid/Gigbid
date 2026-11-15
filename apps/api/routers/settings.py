"""Onboarding, settings, portfolio upload, memory viewer, marketplace status."""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from agent.memory.store import delete_memory, list_memory
from apps.api import services
from apps.api.auth.security import CurrentUser
from apps.api.db import get_settings, put_settings, session
from apps.api.schemas.models import SettingsIn, StatusOut
from mcp_servers.portfolio import tools as portfolio
from rag.index.portfolio_index import add_upload

router = APIRouter(prefix="/api", tags=["settings"])
ALLOWED = (".pdf", ".md", ".txt", ".py", ".ts", ".js", ".sql", ".ipynb", ".json")


@router.get("/settings")
def read(user: str = CurrentUser) -> dict:
    with session() as s:
        return get_settings(s, user)


@router.put("/settings")
def write(body: SettingsIn, user: str = CurrentUser) -> dict:
    data = body.model_dump(exclude_none=True)
    if "persona" in data:
        if data["persona"] not in portfolio.list_owners() + ["own"]:
            raise HTTPException(422, "unknown persona")
        data["owner"] = user if data["persona"] == "own" else data["persona"]
        prof = portfolio.profile(data["owner"])
        data.setdefault("hourly_floor", prof.get("floor", 30))
        data.setdefault("hourly_rate", prof.get("rate", 40))
    if "saved_searches" in data:
        data["saved_searches"] = [x if isinstance(x, dict) else x.model_dump() for x in data["saved_searches"]]
    with session() as s:
        return put_settings(s, user, data)


@router.get("/personas")
def personas() -> list[dict]:
    return [{"id": o, **{k: v for k, v in portfolio.profile(o).items() if k in ("name", "title", "floor", "rate",
                                                                                   "categories")}}
            for o in portfolio.list_owners()]


@router.post("/portfolio/upload")
async def upload(file: UploadFile = File(...), kind: str | None = None, user: str = CurrentUser) -> dict:
    if not file.filename or not file.filename.lower().endswith(ALLOWED):
        raise HTTPException(422, f"allowed types: {', '.join(ALLOWED)}")
    data = await file.read()
    if len(data) > 5_000_000:
        raise HTTPException(413, "file too large (5 MB max)")
    with session() as s:
        owner = get_settings(s, user)["owner"]
    n = add_upload(owner, file.filename, data, kind)
    return {"ok": True, "owner": owner, "new_chunks": n}


@router.post("/portfolio/github")
async def github_repo(repo: str, user: str = CurrentUser) -> dict:
    """Ingest a repo through GitHub's official MCP server (needs GITHUB_TOKEN on the server)."""
    import os
    import re
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise HTTPException(422, "repo must look like owner/name")
    if not os.getenv("GITHUB_TOKEN"):
        raise HTTPException(503, "GitHub MCP server not configured (GITHUB_TOKEN)")
    from rag.ingest.github import ingest_repo
    with session() as s:
        owner = get_settings(s, user)["owner"]
    return {"ok": True, "new_chunks": await ingest_repo(owner, repo)}


@router.get("/portfolio/skills")
def skills(user: str = CurrentUser) -> list[dict]:
    with session() as s:
        owner = get_settings(s, user)["owner"]
    return portfolio.list_skills(owner)


@router.get("/memory")
def memory(user: str = CurrentUser) -> dict:
    return list_memory(user)


@router.delete("/memory/{namespace}/{key:path}")
def forget(namespace: str, key: str, user: str = CurrentUser) -> dict:
    if not delete_memory(user, namespace, key):
        raise HTTPException(404, "memory item not found")
    return {"ok": True}


@router.get("/status", response_model=StatusOut)
async def status() -> StatusOut:
    st = services.marketplace_status()
    return StatusOut(marketplace_available=st["marketplace_available"], degraded=st["degraded"], detail=st["detail"])
