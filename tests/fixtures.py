import os  # noqa: I001
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# deterministic, offline defaults for the whole test session
os.environ.setdefault("GIGBID_PROFILE", "rules")
os.environ.setdefault("GIGBID_EMBEDDER", "hashed-tfidf")
os.environ.setdefault("GIGBID_RERANKER", "lexical")
os.environ.setdefault("MCP_MODE", "inmemory")
os.environ.setdefault("GIGBID_STORE", "memory")
os.environ.setdefault("SIM_ERROR_RATE", "0")
os.environ.setdefault("SIM_RATE_LIMIT_PER_MIN", "100000")
os.environ.setdefault("MARKETPLACE_RATE_PER_MIN", "100000")
os.environ.setdefault("WORKSPACE_NOW", "2026-11-16T09:00:00")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="session", autouse=True)
def data_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("gigbid_data")
    os.environ["GIGBID_DATA_DIR"] = str(d)
    yield d


@pytest.fixture(scope="session")
def sim_url(data_dir):
    import uvicorn

    from sim.app import app
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}"
    os.environ["GIGSIM_URL"] = url
    from mcp_servers.marketplace import server as ms
    ms.ADAPTER.base_url = url
    yield url
    server.should_exit = True


@pytest.fixture()
def sim(sim_url, tmp_path):
    """Fresh simulator world (and a fresh grant/idempotency ledger) for each test."""
    import httpx

    from mcp_servers.marketplace import server as ms
    from mcp_servers.marketplace.approvals import GrantLedger
    ms.LEDGER = GrantLedger(tmp_path / "marketplace_state.db")
    httpx.post(f"{sim_url}/admin/reset", headers={"x-admin-key": "sim-admin"}, params={"error_rate": 0})
    from agent import health
    health.reset()
    from agent.mcp_client import set_gateway
    set_gateway(None)
    yield sim_url


@pytest.fixture()
def fresh_store():
    from langgraph.store.memory import InMemoryStore

    from agent.memory.store import set_store
    st = InMemoryStore()
    set_store(st)
    yield st
    set_store(None)


def user_ctx(account="marvan", owner="ml_engineer"):
    return {"account": account, "owner": owner, "hourly_floor": 35, "hourly_rate": 45, "autonomy": "suggest",
            "weekly_connects_budget": 200, "connects_spent_week": 0}
