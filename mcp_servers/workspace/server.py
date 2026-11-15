"""GigBid Workspace MCP server: calendar slots, tentative interview holds and email drafts.

Backed by a local mock (JSON per account) so it runs anywhere; replacing the store
with Google Calendar / Gmail API calls does not change the tool signatures."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import threading
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from agent.settings import data_dir
from mcp_servers.common import AuditLog

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)

mcp = FastMCP("gigbid-workspace", instructions="Calendar availability, tentative holds and email drafts.",
              stateless_http=True)
AUDIT = AuditLog()
_LOCK = threading.Lock()
Account = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")


def _path(account: str) -> Path:
    return data_dir() / "workspace" / f"{account}.json"


def _load(account: str) -> dict:
    p = _path(account)
    if p.exists():
        return json.loads(p.read_text())
    # default working pattern: weekdays 10:00-18:00 PKT, a standing meeting on Mon/Wed 11:00-12:00
    return {"tz": "Asia/Karachi", "work_hours": [10, 18], "busy": [{"weekday": 0, "start": 11, "end": 12},
                                                                 {"weekday": 2, "start": 11, "end": 12}],
            "holds": [], "drafts": []}


def _save(account: str, data: dict) -> None:
    p = _path(account)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1))


class Slot(BaseModel):
    start: str
    end: str
    label: str


def _now() -> dt.datetime:
    fixed = os.getenv("WORKSPACE_NOW")  # deterministic tests
    return dt.datetime.fromisoformat(fixed) if fixed else dt.datetime.now().replace(second=0, microsecond=0)


@mcp.tool(annotations=READ, structured_output=True)
def free_slots(account: str = Account, days: int = Field(5, ge=1, le=14),
               duration_minutes: int = Field(30, ge=15, le=180), max_slots: int = Field(4, ge=1, le=10)) -> list[Slot]:
    """Free interview slots in the next `days` working days (local time), avoiding busy blocks and existing holds."""
    data = _load(account)
    start_h, end_h = data["work_hours"]
    out: list[Slot] = []
    day = _now().date() + dt.timedelta(days=1)
    holds = [(dt.datetime.fromisoformat(h["start"]), dt.datetime.fromisoformat(h["end"])) for h in data["holds"]]
    while len(out) < max_slots and (day - _now().date()).days <= days + 4:
        if day.weekday() < 5:
            for hour in range(start_h, end_h):
                s = dt.datetime.combine(day, dt.time(hour))
                e = s + dt.timedelta(minutes=duration_minutes)
                busy = any(b["weekday"] == day.weekday() and b["start"] <= hour < b["end"] for b in data["busy"])
                clash = any(s < he and hs < e for hs, he in holds)
                if not busy and not clash and hour in (start_h + 0, start_h + 3, start_h + 6):
                    out.append(Slot(start=s.isoformat(), end=e.isoformat(), label=s.strftime("%a %d %b, %H:%M PKT")))
                    break
        day += dt.timedelta(days=1)
    AUDIT.append(account, "free_slots", {"days": days}, {"n": len(out)})
    return out


@mcp.tool(annotations=WRITE)
def create_interview_hold(account: str = Account, start: str = Field(min_length=16, max_length=32),
                          duration_minutes: int = Field(30, ge=15, le=180), title: str = Field(max_length=120),
                          idempotency_key: str = Field(min_length=8, max_length=128)) -> dict:
    """Create a TENTATIVE calendar hold (not an invitation). Same idempotency key -> same hold."""
    with _LOCK:
        data = _load(account)
        for h in data["holds"]:
            if h["key"] == idempotency_key:
                return {**h, "idempotent_replay": True}
        s = dt.datetime.fromisoformat(start)
        hold = {"id": "h" + hashlib.sha1(idempotency_key.encode()).hexdigest()[:8], "key": idempotency_key,
                "start": s.isoformat(), "end": (s + dt.timedelta(minutes=duration_minutes)).isoformat(),
                "title": title, "status": "tentative"}
        data["holds"].append(hold)
        _save(account, data)
    AUDIT.append(account, "create_interview_hold", {"start": start, "title": title}, hold)
    return hold


@mcp.tool(annotations=WRITE)
def create_email_draft(account: str = Account, to_label: str = Field(max_length=120),
                       subject: str = Field(max_length=200), body: str = Field(max_length=5000)) -> dict:
    """Create an email DRAFT in the user's mailbox (never sent by GigBid)."""
    with _LOCK:
        data = _load(account)
        d = {"id": f"e{len(data['drafts']) + 1}", "to": to_label, "subject": subject, "body": body}
        data["drafts"].append(d)
        _save(account, data)
    AUDIT.append(account, "create_email_draft", {"to": to_label, "subject": subject}, {"id": d["id"]})
    return d


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.getenv("PORT", "8203")))
    args = ap.parse_args()
    import uvicorn

    from mcp_servers.common import http_auth_app
    uvicorn.run(http_auth_app(mcp.streamable_http_app(), "workspace"), host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
