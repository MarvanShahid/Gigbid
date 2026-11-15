"""Shared helpers for evaluation runners: environment, dev set, in-process GigSim, metrics, result files."""
from __future__ import annotations

import json
import math
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
RESULTS = ROOT / "evals" / "results"
PERSONAS = ["ml_engineer", "fullstack_dev", "data_analyst"]


def setup_env(profile: str | None = None) -> None:
    os.environ.setdefault("GIGBID_PROFILE", profile or "rules")
    if profile:
        os.environ["GIGBID_PROFILE"] = profile
    os.environ.setdefault("MCP_MODE", "inmemory")
    os.environ.setdefault("GIGBID_STORE", "memory")
    os.environ.setdefault("SIM_ERROR_RATE", "0")
    os.environ.setdefault("SIM_RATE_LIMIT_PER_MIN", "1000000")
    os.environ.setdefault("MARKETPLACE_RATE_PER_MIN", "1000000")
    os.environ.setdefault("GIGBID_DATA_DIR", str(ROOT / "data" / "processed" / "eval"))


def dev_set(persona: str, limit: int | None = None) -> list[dict]:
    jobs = json.loads((ROOT / "evals" / "datasets" / f"dev_{persona}.json").read_text())
    return jobs[:limit] if limit else jobs


def start_sim() -> str:
    import uvicorn

    from sim.app import app
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}"
    os.environ["GIGSIM_URL"] = url
    from mcp_servers.marketplace import server as ms
    ms.ADAPTER.base_url = url
    return url


def commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL).decode().strip()
    except Exception:  # noqa: BLE001
        return "uncommitted"


def meta(**extra) -> dict:
    from agent.settings import profile_name
    from rag.index.embed import get_embedder, get_reranker
    return {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "commit": commit(), "profile": profile_name(),
            "embedder": get_embedder().name, "reranker": get_reranker().name,
            "data": "synthetic stand-in (scripts/build_standin_data.py, seed 800)", **extra}


def write(name: str, payload: dict) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    p = RESULTS / name
    p.write_text(json.dumps(payload, indent=1, default=float))
    print(f"wrote {p.relative_to(ROOT)}")
    return p


def percentile(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    f, c = math.floor(k), math.ceil(k)
    return xs[f] if f == c else xs[f] + (xs[c] - xs[f]) * (k - f)


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0,
            "tp": tp, "fp": fp, "fn": fn}
