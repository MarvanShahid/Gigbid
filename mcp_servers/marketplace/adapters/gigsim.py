"""HTTP adapter from the Marketplace MCP server to the GigSim (stand-in) REST API.

Handles GigSim's 429 (honours Retry-After once) and 5xx (bounded retries with
backoff). Raises MarketplaceError with a stable `kind` so callers can tell a
user error from an outage."""
from __future__ import annotations

import os
import time

import httpx

from agent.observability import trace_headers


class MarketplaceError(Exception):
    def __init__(self, kind: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.kind, self.status = kind, status   # kind: unavailable | rate_limited | rejected | not_found


class GigSimAdapter:
    def __init__(self, base_url: str | None = None, transport: httpx.BaseTransport | None = None) -> None:
        self.base_url = (base_url or os.getenv("GIGSIM_URL", "http://localhost:8100")).rstrip("/")
        self.transport = transport
        self.retries = int(os.getenv("GIGSIM_RETRIES", "3"))

    def _token(self, account: str) -> str:
        return os.getenv(f"GIGSIM_TOKEN_{account.upper().replace('-', '_')}", f"gigsim-dev-{account}")

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, timeout=15, transport=self.transport)

    def request(self, account: str, method: str, path: str, **kw) -> dict:
        headers = {"Authorization": f"Bearer {self._token(account)}", **trace_headers()}
        delay = 0.4
        last = None
        for attempt in range(self.retries + 1):
            try:
                with self._client() as c:
                    r = c.request(method, path, headers=headers, **kw)
            except httpx.TransportError as e:
                last = MarketplaceError("unavailable", f"GigSim unreachable: {e}")
            else:
                if r.status_code == 429:
                    wait = min(float(r.headers.get("Retry-After", "2")), 10.0)
                    last = MarketplaceError("rate_limited", "GigSim rate limit", 429)
                    if attempt < self.retries:
                        time.sleep(wait)
                        continue
                elif r.status_code >= 500:
                    last = MarketplaceError("unavailable", f"GigSim {r.status_code}", r.status_code)
                elif r.status_code == 404:
                    raise MarketplaceError("not_found", r.json().get("detail", "not found"), 404)
                elif r.status_code >= 400:
                    raise MarketplaceError("rejected", str(r.json().get("detail", r.text)), r.status_code)
                else:
                    return r.json()
            if attempt < self.retries:
                time.sleep(delay)
                delay *= 2
        raise last or MarketplaceError("unavailable", "unknown error")

    # read
    def search_jobs(self, account, query="", category=None, limit=20, min_budget=0):
        return self.request(account, "GET", "/jobs", params={k: v for k, v in dict(
            q=query, category=category, limit=limit, min_budget=min_budget).items() if v not in (None, "")})

    def get_job(self, account, job_id):
        return self.request(account, "GET", f"/jobs/{job_id}")

    def get_client(self, account, client_id):
        return self.request(account, "GET", f"/clients/{client_id}")

    def connects(self, account):
        return self.request(account, "GET", "/connects")

    def market_stats(self, account, category):
        return self.request(account, "GET", "/market/stats", params={"category": category})

    def policy(self, account):
        return self.request(account, "GET", "/policy")

    def list_messages(self, account):
        return self.request(account, "GET", "/messages")

    def list_proposals(self, account):
        return self.request(account, "GET", "/proposals")

    # write
    def submit_proposal(self, account, payload):
        return self.request(account, "POST", "/proposals", json=payload)

    def send_message(self, account, payload):
        return self.request(account, "POST", "/messages", json=payload)
