"""Model routing by node (config only), token/cost accounting and a fallback model.

`structured(node, schema, system, user)` returns (parsed_model, usage). If the
active profile has no model for this node (profile `rules`), NoModel is raised
and the node uses its deterministic implementation instead.
"""
from __future__ import annotations

import os
import time
from typing import TypeVar

from pydantic import BaseModel

from agent.observability import span
from agent.settings import profile

T = TypeVar("T", bound=BaseModel)
CHEAP_NODES = {"analyst", "risk", "researcher", "verifier", "intent"}


class NoModel(Exception):
    pass


def node_model(node: str) -> dict | None:
    p = profile()
    if p.get("provider") in (None, "none"):
        return None
    return p.get("nodes", {}).get(node)


def has_model(node: str) -> bool:
    return node_model(node) is not None and bool(os.getenv(profile().get("api_key_env", ""), "")
                                                 or profile().get("provider") == "ollama")


def _chat(model: str, temperature: float):
    from langchain_openai import ChatOpenAI
    p = profile()
    return ChatOpenAI(model=model, temperature=temperature, base_url=p["base_url"],
                      api_key=os.getenv(p.get("api_key_env", ""), "ollama"), timeout=60, max_retries=2)


def cost_usd(model: str, tin: int, tout: int) -> float:
    price = profile().get("usd_per_mtok", {}).get(model)
    if not price:
        return 0.0
    return (tin * price[0] + tout * price[1]) / 1e6


def _invoke(node: str, model: str, temperature: float, schema, messages):
    llm = _chat(model, temperature)
    if schema is not None:
        runnable = llm.with_structured_output(schema, method="function_calling", include_raw=True)
        out = runnable.invoke(messages)
        raw, parsed = out["raw"], out["parsed"]
        if parsed is None:
            raise ValueError(f"{node}: model returned unparsable output: {out.get('parsing_error')}")
    else:
        raw = llm.invoke(messages)
        parsed = raw.content
    um = getattr(raw, "usage_metadata", None) or {}
    return parsed, int(um.get("input_tokens", 0)), int(um.get("output_tokens", 0))


def call(node: str, system: str, user: str, schema: type[T] | None = None):
    """Returns (result, usage dict). Raises NoModel when the profile has no model for the node."""
    spec = node_model(node)
    if spec is None or not has_model(node):
        raise NoModel(node)
    messages = [("system", system), ("user", user)]
    model, temp = spec["model"], float(spec.get("temperature", 0))
    t0 = time.perf_counter()
    with span(f"llm.{node}", node=node, model=model) as sp:
        try:
            parsed, tin, tout = _invoke(node, model, temp, schema, messages)
        except Exception as e:  # noqa: BLE001
            fb = profile().get("fallback_model")
            if node not in CHEAP_NODES or not fb or fb == model:
                sp.set_attribute("error", str(e)[:300])
                raise
            sp.set_attribute("fallback_from", model)
            model = fb
            parsed, tin, tout = _invoke(node, model, temp, schema, messages)
        usd = cost_usd(model, tin, tout)
        sp.set_attribute("tokens_in", tin)
        sp.set_attribute("tokens_out", tout)
        sp.set_attribute("cost_usd", usd)
        sp.set_attribute("model_used", model)
    return parsed, {"tokens": tin + tout, "cost_usd": usd, "model": model,
                    "latency_s": round(time.perf_counter() - t0, 3)}
