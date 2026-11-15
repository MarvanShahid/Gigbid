"""Retriever factory: the variant is chosen by config (rag.variant), never hard-coded."""
from __future__ import annotations

import importlib
import os

from agent.settings import config
from rag.index.portfolio_index import get_index
from rag.variants.base import Pipeline, RetrievalResult

VARIANTS = ["v0_naive", "v1_decompose", "v2_hybrid", "v3_rerank", "v4_outcome", "v5_multivector",
            "v6_contextual", "v7_hyde", "v8_corrective", "v_best"]


def build_variant(name: str | None = None, **kw) -> Pipeline:
    name = name or os.getenv("GIGBID_RAG_VARIANT") or config()["rag"]["variant"]
    if name not in VARIANTS:
        raise ValueError(f"unknown variant {name}")
    return importlib.import_module(f"rag.variants.{name}").build(**kw)


def retrieve(owner: str, job_text: str, requirements: list[str] | None = None, k: int | None = None,
             variant: str | None = None) -> RetrievalResult:
    return build_variant(variant).retrieve(get_index(owner), job_text, requirements, k or config()["rag"]["k"])
