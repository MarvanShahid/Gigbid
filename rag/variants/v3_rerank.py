"""V3: Hybrid candidates re-scored by an open cross-encoder (precision at small k)."""
from .base import Pipeline, PipelineConfig

CONFIG = PipelineConfig(name="v3_rerank", hybrid=True, rerank=True)


def build(**kw) -> Pipeline:
    return Pipeline(CONFIG, **kw)
