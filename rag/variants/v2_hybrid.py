"""V2: Hybrid BM25 + dense with reciprocal rank fusion (exact tool names such as dbt or Celery)."""
from .base import Pipeline, PipelineConfig

CONFIG = PipelineConfig(name="v2_hybrid", hybrid=True)


def build(**kw) -> Pipeline:
    return Pipeline(CONFIG, **kw)
