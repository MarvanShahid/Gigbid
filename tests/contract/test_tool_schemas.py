"""Schema snapshot test (A7): fails when a tool signature changes unintentionally.
After an intended change run:  python -m tests.contract.test_tool_schemas --update"""
import asyncio
import json
import sys
from pathlib import Path

from mcp.shared.memory import create_connected_server_and_client_session

SNAP = Path(__file__).with_name("tool_schemas.snapshot.json")


async def current() -> dict:
    from mcp_servers.marketplace.server import mcp as m
    from mcp_servers.portfolio.server import mcp as p
    from mcp_servers.workspace.server import mcp as w
    out = {}
    for name, srv in (("portfolio", p), ("marketplace", m), ("workspace", w)):
        async with create_connected_server_and_client_session(srv) as s:
            for t in (await s.list_tools()).tools:
                out[f"{name}.{t.name}"] = {"input": t.inputSchema, "output": t.outputSchema,
                                           "annotations": t.annotations.model_dump() if t.annotations else None}
    return out


def test_tool_schemas_match_snapshot():
    cur = asyncio.run(current())
    assert SNAP.exists(), "run with --update to create the snapshot"
    snap = json.loads(SNAP.read_text())
    changed = sorted(k for k in set(cur) | set(snap) if cur.get(k) != snap.get(k))
    assert not changed, f"tool signatures changed: {changed}. If intended, run with --update and commit."


if __name__ == "__main__" and "--update" in sys.argv:
    SNAP.write_text(json.dumps(asyncio.run(current()), indent=1, sort_keys=True))
    print(f"wrote {SNAP}")
