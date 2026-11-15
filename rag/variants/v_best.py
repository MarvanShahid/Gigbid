"""Shipped pipeline, chosen by evals/runners/rag_eval.py (see docs/RESULTS.md).

Components are switched in agent/config.yaml (rag.best); the ablation runner removes
one at a time."""
from agent.settings import config

from .base import Pipeline, PipelineConfig

DEFAULT = dict(decompose=False, hybrid=True, multivector=True, outcome=True, corrective=True, rerank=True)


def build(**kw) -> Pipeline:
    flags = {**DEFAULT, **(config().get("rag", {}).get("best") or {})}
    return Pipeline(PipelineConfig(name="v_best", **flags), **kw)
