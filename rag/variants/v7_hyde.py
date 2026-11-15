"""V7: HyDE: retrieve with a hypothetical ideal proposal for the job."""
from .base import Pipeline, PipelineConfig

CONFIG = PipelineConfig(name="v7_hyde", hyde=True)


def build(**kw) -> Pipeline:
    return Pipeline(CONFIG, **kw)
