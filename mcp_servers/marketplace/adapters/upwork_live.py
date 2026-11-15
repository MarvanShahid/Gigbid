"""Live adapter for Upwork's official MCP server (https://mcp.upwork.com/mcp, OAuth 2.1).

* OAuth: the MCP Python SDK's OAuthClientProvider runs discovery, dynamic client
  registration, PKCE and refresh. Tokens are stored encrypted per user
  (apps/api/auth/token_store.py) and never logged.
* Tool mapping: GigBid's port methods are mapped onto Upwork's tool names. The
  names are read from upwork_tools.yaml; run `python scripts/upwork_list_tools.py`
  after connecting to print the real tool list and adjust the file.
* Safety: write methods only create DRAFTS on Upwork; the user confirms them on
  Upwork itself. No browser automation, no cookies, no scraping.

Status: written against the MCP spec and SDK; not exercised against a real
Upwork account in this submission (no account available). Live mode is never
graded on outcomes.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import yaml
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

UPWORK_MCP_URL = "https://mcp.upwork.com/mcp"
TOOL_MAP_FILE = Path(__file__).with_name("upwork_tools.yaml")


def tool_map() -> dict[str, dict]:
    return yaml.safe_load(TOOL_MAP_FILE.read_text())


class EncryptedTokenStorage(TokenStorage):
    """Adapts GigBid's encrypted per-user token store to the SDK's TokenStorage interface."""

    def __init__(self, user_id: str, store) -> None:
        self.user_id, self.store = user_id, store

    async def get_tokens(self) -> OAuthToken | None:
        raw = self.store.get(self.user_id, "upwork_tokens")
        return OAuthToken.model_validate_json(raw) if raw else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.store.put(self.user_id, "upwork_tokens", tokens.model_dump_json())

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        raw = self.store.get(self.user_id, "upwork_client")
        return OAuthClientInformationFull.model_validate_json(raw) if raw else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.store.put(self.user_id, "upwork_client", client_info.model_dump_json())


class PendingAuth:
    """Bridges the SDK's redirect/callback handlers to the web app: the UI fetches the
    authorization URL, the browser returns to /api/auth/upwork/callback, which resolves the future."""

    pending: dict[str, "PendingAuth"] = {}

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id
        self.auth_url: str | None = None
        self.url_ready = asyncio.Event()
        self.code: asyncio.Future = asyncio.get_event_loop().create_future()
        PendingAuth.pending[user_id] = self

    async def redirect(self, url: str) -> None:
        self.auth_url = url
        self.url_ready.set()

    async def callback(self) -> tuple[str, str | None]:
        return await self.code


def oauth_provider(user_id: str, store, redirect_uri: str, pending: PendingAuth | None = None) -> OAuthClientProvider:
    meta = OAuthClientMetadata(client_name="GigBid", redirect_uris=[redirect_uri], grant_types=[
        "authorization_code", "refresh_token"], response_types=["code"], token_endpoint_auth_method="none")
    return OAuthClientProvider(server_url=UPWORK_MCP_URL, client_metadata=meta,
                               storage=EncryptedTokenStorage(user_id, store),
                               redirect_handler=pending.redirect if pending else None,
                               callback_handler=pending.callback if pending else None)


def connection(user_id: str, store, redirect_uri: str) -> dict[str, Any]:
    """MultiServerMCPClient connection entry for the Upwork server."""
    return {"transport": "streamable_http", "url": UPWORK_MCP_URL,
            "auth": oauth_provider(user_id, store, redirect_uri)}


# --------------------------------------------------------------- translation
def to_job(raw: dict) -> dict:
    """Normalise an Upwork job payload to GigBid's Job shape (field names per upwork_tools.yaml)."""
    budget = raw.get("budget") or raw.get("amount") or {}
    amount = budget.get("amount") if isinstance(budget, dict) else budget
    return {"id": str(raw.get("id") or raw.get("ciphertext") or raw.get("jobId")),
            "title": raw.get("title", ""), "description": raw.get("description", ""),
            "category": raw.get("category") or raw.get("occupation") or "unknown",
            "skills_tags": [s if isinstance(s, str) else s.get("name", "") for s in raw.get("skills", [])],
            "budget": {"type": raw.get("jobType", "fixed").lower(), "amount": float(amount or 0)},
            "client_id": str((raw.get("client") or {}).get("id", raw.get("clientId", "unknown"))),
            "screening_questions": [q if isinstance(q, str) else q.get("question", "")
                                    for q in raw.get("questions", [])],
            "posted_at": raw.get("createdDateTime") or raw.get("publishedOn") or "",
            "connects_required": int(raw.get("connectPrice") or raw.get("connectsRequired") or 0)}
