"""V0: Naive dense: fixed 400-char chunks, top-k cosine on the whole job post."""
from .base import Pipeline, PipelineConfig

CONFIG = PipelineConfig(name="v0_naive", chunkset="fixed", evidence_only=False)


def build(**kw) -> Pipeline:
    return Pipeline(CONFIG, **kw)
