import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from mcp_servers.portfolio.server import mcp


@pytest.mark.asyncio
async def test_search_evidence_returns_typed_items():
    async with create_connected_server_and_client_session(mcp) as s:
        r = await s.call_tool("search_evidence", {"requirement": "PyTorch model training", "k": 3,
                                                  "owner": "ml_engineer"})
    assert not r.isError
    items = r.structuredContent["result"]
    assert 1 <= len(items) <= 3
    assert {"id", "type", "source", "date", "outcome"} <= set(items[0])


@pytest.mark.asyncio
async def test_filters_apply():
    async with create_connected_server_and_client_session(mcp) as s:
        r = await s.call_tool("search_evidence", {"requirement": "Docker", "k": 5, "owner": "ml_engineer",
                                                  "filters": {"types": ["code"]}})
    assert all(i["type"] == "code" for i in r.structuredContent["result"])


@pytest.mark.asyncio
async def test_resources_and_prompts():
    async with create_connected_server_and_client_session(mcp) as s:
        templates = [t.uriTemplate for t in (await s.list_resource_templates()).resourceTemplates]
        assert "portfolio://case/{case_id}" in templates and "portfolio://proposal/{proposal_id}" in templates
        prompts = [p.name for p in (await s.list_prompts()).prompts]
        assert "answer_screening_question" in prompts
        res = await s.read_resource("portfolio://case/ml-p01")
        assert json.loads(res.contents[0].text)["id"] == "ml-p01"


@pytest.mark.asyncio
async def test_list_skills():
    async with create_connected_server_and_client_session(mcp) as s:
        r = await s.call_tool("list_skills", {"owner": "data_analyst"})
    skills = [x["skill"] for x in json.loads(r.content[0].text)] if r.structuredContent is None else \
        [x["skill"] for x in r.structuredContent["result"]]
    assert "sql" in skills
