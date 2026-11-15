"""V6: Contextual retrieval: structured chunks keep their project title as a context line; queries are framed as evidence requests."""
from .base import Pipeline, PipelineConfig

CONFIG = PipelineConfig(name="v6_contextual", contextual=True)


def build(**kw) -> Pipeline:
    return Pipeline(CONFIG, **kw)
