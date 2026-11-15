"""After connecting Upwork in the UI (OAuth), print the official MCP server's real tool list so
mcp_servers/marketplace/adapters/upwork_tools.yaml can be checked against it.

    python scripts/upwork_list_tools.py --user <gigbid user id>
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main(user: str) -> None:
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    from apps.api.auth.token_store import TokenStore
    from mcp_servers.marketplace.adapters.upwork_live import UPWORK_MCP_URL, oauth_provider
    prov = oauth_provider(user, TokenStore(), os.getenv("UPWORK_REDIRECT_URI", "http://localhost:8000/api/auth/upwork/callback"))
    async with streamablehttp_client(UPWORK_MCP_URL, auth=prov) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            for t in (await s.list_tools()).tools:
                ro = t.annotations.readOnlyHint if t.annotations else None
                print(f"{t.name:40s} readOnly={ro}  {(t.description or '')[:90]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    asyncio.run(main(ap.parse_args().user))
