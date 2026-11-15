"""V1: Requirement decomposition: one dense retrieval per extracted requirement, merged with RRF."""
from .base import Pipeline, PipelineConfig

CONFIG = PipelineConfig(name="v1_decompose", decompose=True)


def build(**kw) -> Pipeline:
    return Pipeline(CONFIG, **kw)
