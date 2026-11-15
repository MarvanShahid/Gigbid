"""V5: Multi-vector items: summary, README and code indexed separately, returned as one project."""
from .base import Pipeline, PipelineConfig

CONFIG = PipelineConfig(name="v5_multivector", hybrid=True, multivector=True)


def build(**kw) -> Pipeline:
    return Pipeline(CONFIG, **kw)
