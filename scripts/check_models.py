"""Check that every model in agent/config.yaml exists on your Groq account.

    python scripts\\check_models.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from agent.settings import config  # noqa: E402

key = os.getenv("GROQ_API_KEY")
if not key:
    sys.exit("GROQ_API_KEY is not set (check .env)")
r = httpx.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {key}"}, timeout=20)
r.raise_for_status()
available = sorted(m["id"] for m in r.json()["data"])
print("Models on your Groq account:")
for m in available:
    print("  ", m)
print()
for name in ("open", "open_alt"):
    p = config()["profiles"][name]
    used = {v["model"] for v in p["nodes"].values()} | {p.get("fallback_model")}
    for m in sorted(x for x in used if x):
        print(f"[{name}] {m:35s} {'OK' if m in available else 'NOT AVAILABLE -> change it in agent/config.yaml'}")
