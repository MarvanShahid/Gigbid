"""Shared pieces for GigBid's own MCP servers: bearer auth, per-user rate limiting,
append-only audit log and trace-id propagation."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from agent.observability import get_trace_id, mask_pii, set_trace_id
from agent.settings import data_dir


class AuditLog:
    """Append-only JSONL audit log. Each line is chained to the previous one with a
    SHA-256 hash so silent edits are detectable (`verify()`)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_dir() / "audit.jsonl"
        self.lock = threading.Lock()

    def _last_hash(self) -> str:
        if not self.path.exists():
            return "0" * 64
        last = ""
        with open(self.path, "rb") as f:
            for line in f:
                if line.strip():
                    last = line
        return json.loads(last)["hash"] if last else "0" * 64

    def append(self, user: str, tool: str, arguments: dict, result: Any, ok: bool = True) -> dict:
        with self.lock:
            rec = {"ts": time.time(), "user": user, "tool": tool, "arguments": mask_pii(arguments),
                   "result": mask_pii(result), "ok": ok, "trace_id": get_trace_id(), "prev": self._last_hash()}
            rec["hash"] = hashlib.sha256(json.dumps(rec, sort_keys=True, default=str).encode()).hexdigest()
            with open(self.path, "a") as f:
                f.write(json.dumps(rec, default=str) + "\n")
            return rec

    def verify(self) -> bool:
        prev = "0" * 64
        if not self.path.exists():
            return True
        for line in self.path.read_text().splitlines():
            rec = json.loads(line)
            h = rec.pop("hash")
            if rec["prev"] != prev or hashlib.sha256(json.dumps(rec, sort_keys=True, default=str).encode()).hexdigest() != h:
                return False
            prev = h
        return True

    def records(self, tool: str | None = None) -> list[dict]:
        if not self.path.exists():
            return []
        rows = [json.loads(x) for x in self.path.read_text().splitlines() if x.strip()]
        return [r for r in rows if tool is None or r["tool"] == tool]


class RateLimiter:
    """Token bucket per user. Defaults keep us at ~80% of GigSim's per-token limit."""

    def __init__(self, per_minute: int | None = None) -> None:
        self.rate = (per_minute or int(os.getenv("MARKETPLACE_RATE_PER_MIN", "48"))) / 60.0
        self.capacity = max(1.0, self.rate * 10)
        self.state: dict[str, tuple[float, float]] = defaultdict(lambda: (self.capacity, time.monotonic()))
        self.lock = threading.Lock()

    def acquire(self, user: str, block: bool = True) -> bool:
        while True:
            with self.lock:
                tokens, ts = self.state[user]
                now = time.monotonic()
                tokens = min(self.capacity, tokens + (now - ts) * self.rate)
                if tokens >= 1:
                    self.state[user] = (tokens - 1, now)
                    return True
                self.state[user] = (tokens, now)
                wait = (1 - tokens) / self.rate
            if not block:
                return False
            time.sleep(min(wait, 2.0))


def bearer_tokens() -> dict[str, str]:
    """token -> user id, from MCP_TOKENS="user1:token1,user2:token2"."""
    raw = os.getenv("MCP_TOKENS", "")
    out = {}
    for pair in filter(None, raw.split(",")):
        user, _, tok = pair.partition(":")
        out[tok.strip()] = user.strip()
    return out


def http_auth_app(app, server_name: str):
    """Wrap a Starlette ASGI app with bearer-token auth and trace-id extraction."""
    tokens = bearer_tokens()

    async def wrapped(scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            if scope.get("path", "").rstrip("/") not in ("/health",):
                auth = headers.get("authorization", "")
                tok = auth[7:] if auth.startswith("Bearer ") else ""
                if not tok or (tokens and tok not in tokens):
                    body = json.dumps({"error": f"{server_name}: unauthorized"}).encode()
                    await send({"type": "http.response.start", "status": 401,
                                "headers": [(b"content-type", b"application/json")]})
                    await send({"type": "http.response.body", "body": body})
                    return
                scope.setdefault("state", {})["user"] = tokens.get(tok, "dev")
            if headers.get("x-trace-id"):
                set_trace_id(headers["x-trace-id"])
        await app(scope, receive, send)

    return wrapped
