"""Repo ingestion through GitHub's official MCP server (third-party server #2, A5/B1).

    GITHUB_TOKEN=... python -m rag.ingest.github --owner <user> owner/repo [owner/repo2 ...]

We never clone or scrape: the server's `get_file_contents` tool returns the README and the
source files we ask for; each becomes structured + fixed chunks with the repo as the project,
and is indexed incrementally (only new chunk ids are embedded).
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os

from rag.index.portfolio_index import get_index
from rag.ingest.loaders import chunks_from_upload

GITHUB_MCP_URL = os.getenv("GITHUB_MCP_URL", "https://api.githubcopilot.com/mcp/")
CODE_EXT = (".py", ".ts", ".tsx", ".js", ".sql", ".ipynb", ".md")


def _text(result) -> str:
    sc = getattr(result, "structuredContent", None)
    if sc and isinstance(sc, dict) and sc.get("content"):
        c = sc["content"]
        return base64.b64decode(c).decode(errors="ignore") if sc.get("encoding") == "base64" else c
    parts = []
    for c in result.content:
        if getattr(c, "text", None):
            parts.append(c.text)
        elif getattr(c, "resource", None) is not None and getattr(c.resource, "text", None):
            parts.append(c.resource.text)
    return "\n".join(parts)


async def ingest_repo(owner_id: str, repo: str, max_files: int = 25) -> int:
    from langchain_mcp_adapters.client import MultiServerMCPClient
    token = os.environ["GITHUB_TOKEN"]
    client = MultiServerMCPClient({"github": {"transport": "streamable_http", "url": GITHUB_MCP_URL,
                                              "headers": {"Authorization": f"Bearer {token}"}}})
    gh_owner, name = repo.split("/", 1)
    added = 0
    idx = get_index(owner_id)
    async with client.session("github") as s:
        readme = await s.call_tool("get_file_contents", {"owner": gh_owner, "repo": name, "path": "README.md"})
        if not readme.isError:
            added += idx.add(chunks_from_upload(owner_id, f"{name}/README.md", _text(readme).encode(), "readme"))
        listing = await s.call_tool("get_file_contents", {"owner": gh_owner, "repo": name, "path": ""})
        files = []
        try:
            entries = json.loads(_text(listing))
            files = [e["path"] for e in entries if e.get("type") == "file" and e["path"].endswith(CODE_EXT)]
        except (json.JSONDecodeError, TypeError, KeyError):
            pass
        for path in files[:max_files]:
            r = await s.call_tool("get_file_contents", {"owner": gh_owner, "repo": name, "path": path})
            if not r.isError:
                added += idx.add(chunks_from_upload(owner_id, f"{name}/{path}", _text(r).encode(), "code"))
    return added


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", required=True, help="GigBid portfolio owner id")
    ap.add_argument("repos", nargs="+")
    a = ap.parse_args()
    for rp in a.repos:
        print(rp, asyncio.run(ingest_repo(a.owner, rp)), "new chunks")
