"""Shared health status of MCP servers (degraded mode, A6). Uses Redis when
REDIS_URL is set so the API, worker and UI agree; otherwise process memory."""
from __future__ import annotations

import json
import os
import time

_MEM: dict[str, dict] = {}


def _redis():
    url = os.getenv("REDIS_URL")
    if not url:
        return None
    try:
        import redis
        r = redis.Redis.from_url(url, socket_connect_timeout=0.5, socket_timeout=0.5)
        r.ping()
        return r
    except Exception:  # noqa: BLE001
        return None


def mark(server: str, ok: bool, error: str | None = None) -> None:
    rec = {"ok": ok, "error": error, "at": time.time()}
    r = _redis()
    prev = status().get(server, {})
    if prev.get("ok") == ok and ok:
        return
    rec["since"] = prev.get("since", rec["at"]) if prev.get("ok") == ok else rec["at"]
    if r:
        r.hset("gigbid:health", server, json.dumps(rec))
    _MEM[server] = rec


def status() -> dict[str, dict]:
    r = _redis()
    if r:
        try:
            return {k.decode(): json.loads(v) for k, v in r.hgetall("gigbid:health").items()}
        except Exception:  # noqa: BLE001
            pass
    return dict(_MEM)


def degraded() -> list[str]:
    return [s for s, v in status().items() if not v.get("ok", True)]


def reset() -> None:
    _MEM.clear()
    r = _redis()
    if r:
        r.delete("gigbid:health")
