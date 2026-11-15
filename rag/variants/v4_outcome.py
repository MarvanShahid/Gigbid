"""V4: Outcome-aware ranking: boost projects cited by past proposals that won or got replies."""
from .base import Pipeline, PipelineConfig

CONFIG = PipelineConfig(name="v4_outcome", hybrid=True, outcome=True)


def build(**kw) -> Pipeline:
    return Pipeline(CONFIG, **kw)
