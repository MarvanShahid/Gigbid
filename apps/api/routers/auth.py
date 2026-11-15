"""Sign-in, registration, Upwork OAuth (live mode)."""
from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from apps.api.auth.security import CurrentUser, create_user, issue_token, verify_password
from apps.api.auth.token_store import TokenStore
from apps.api.db import User, get_settings, session
from apps.api.schemas.models import LoginIn, Me, RegisterIn, TokenOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut)
def register(body: RegisterIn, response: Response) -> TokenOut:
    u = create_user(body.email, body.password, body.name)
    tok = issue_token(u.id)
    response.set_cookie("gigbid_session", tok, httponly=True, samesite="lax")
    return TokenOut(token=tok, user_id=u.id, name=u.name)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, response: Response) -> TokenOut:
    with session() as s:
        u = s.scalar(select(User).where(User.email == body.email.lower()))
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "wrong email or password")
    tok = issue_token(u.id)
    response.set_cookie("gigbid_session", tok, httponly=True, samesite="lax")
    return TokenOut(token=tok, user_id=u.id, name=u.name)


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie("gigbid_session")
    return {"ok": True}


@router.get("/me", response_model=Me)
def me(user: str = CurrentUser) -> Me:
    with session() as s:
        u = s.get(User, user)
        if not u:
            raise HTTPException(401, "unknown user")
        return Me(user_id=u.id, email=u.email, name=u.name, settings=get_settings(s, user))


@router.get("/upwork/start")
async def upwork_start(user: str = CurrentUser) -> dict:
    """Begin the OAuth 2.1 flow with Upwork's MCP server; returns the URL to open in the browser."""
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    from mcp_servers.marketplace.adapters.upwork_live import UPWORK_MCP_URL, PendingAuth, oauth_provider
    pending = PendingAuth(user)
    redirect = os.getenv("UPWORK_REDIRECT_URI", "http://localhost:8000/api/auth/upwork/callback")
    provider = oauth_provider(user, TokenStore(), redirect, pending)

    async def connect():
        async with streamablehttp_client(UPWORK_MCP_URL, auth=provider) as (r, w, _):
            async with ClientSession(r, w) as sess:
                await sess.initialize()
    task = asyncio.create_task(connect())
    try:
        await asyncio.wait_for(pending.url_ready.wait(), 20)
    except asyncio.TimeoutError as e:
        task.cancel()
        raise HTTPException(502, "Upwork MCP server did not start an authorization flow") from e
    return {"authorization_url": pending.auth_url}


@router.get("/upwork/callback")
async def upwork_callback(code: str, state: str | None = None, user: str = CurrentUser) -> dict:
    from mcp_servers.marketplace.adapters.upwork_live import PendingAuth
    p = PendingAuth.pending.get(user)
    if not p:
        raise HTTPException(400, "no Upwork authorization in progress")
    p.code.set_result((code, state))
    return {"ok": True, "detail": "Upwork connected. Tokens are stored encrypted."}


@router.get("/connections")
def connections(user: str = CurrentUser) -> dict:
    names = TokenStore().names(user)
    return {"gigsim": True, "upwork": "upwork_tokens" in names}


@router.delete("/connections/upwork")
def disconnect_upwork(user: str = CurrentUser) -> dict:
    ts = TokenStore()
    ts.delete(user, "upwork_tokens")
    ts.delete(user, "upwork_client")
    return {"ok": True}
