import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from mcp_servers.workspace.server import mcp


@pytest.mark.asyncio
async def test_slots_hold_and_draft():
    async with create_connected_server_and_client_session(mcp) as s:
        slots = (await s.call_tool("free_slots", {"account": "ws1", "days": 5})).structuredContent["result"]
        assert slots and all("PKT" in x["label"] for x in slots)
        h1 = await s.call_tool("create_interview_hold", {"account": "ws1", "start": slots[0]["start"], "title": "Call",
                                                         "idempotency_key": "hold-0001"})
        h2 = await s.call_tool("create_interview_hold", {"account": "ws1", "start": slots[0]["start"], "title": "Call",
                                                         "idempotency_key": "hold-0001"})
        assert not h1.isError and "idempotent_replay" in h2.content[0].text
        again = (await s.call_tool("free_slots", {"account": "ws1", "days": 5})).structuredContent["result"]
        assert slots[0]["start"] not in [x["start"] for x in again]
        d = await s.call_tool("create_email_draft", {"account": "ws1", "to_label": "client", "subject": "Hi", "body": "x"})
        assert not d.isError
