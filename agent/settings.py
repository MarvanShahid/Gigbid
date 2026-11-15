"""Load agent/config.yaml with ${ENV:-default} substitution."""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
_ENV = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def _subst(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV.sub(lambda m: os.getenv(m.group(1), m.group(2) or ""), value)
    if isinstance(value, dict):
        return {k: _subst(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_subst(v) for v in value]
    return value


@lru_cache(maxsize=1)
def config() -> dict:
    path = Path(os.getenv("GIGBID_CONFIG", ROOT / "agent" / "config.yaml"))
    return _subst(yaml.safe_load(path.read_text()))


def profile_name() -> str:
    return os.getenv("GIGBID_PROFILE", "open")


def profile() -> dict:
    cfg = config()["profiles"]
    p = dict(cfg[profile_name()])
    if "inherit" in p:
        base = dict(cfg[p["inherit"]])
        base_nodes = dict(base.get("nodes", {}))
        base_nodes.update(p.get("nodes", {}))
        base.update({k: v for k, v in p.items() if k != "nodes"})
        base["nodes"] = base_nodes
        p = base
    return p


def reset_cache() -> None:
    config.cache_clear()


def data_dir() -> Path:
    d = Path(os.getenv("GIGBID_DATA_DIR", ROOT / "data" / "processed"))
    d.mkdir(parents=True, exist_ok=True)
    return d
