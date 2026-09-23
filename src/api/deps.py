from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from src.config import Settings, get_settings
from src.pipeline import Pipeline, build_pipeline


@lru_cache
def _pipeline() -> Pipeline:
    return build_pipeline(get_settings())


def get_pipeline() -> Pipeline:
    return _pipeline()


SettingsDep = Annotated[Settings, Depends(get_settings)]
PipelineDep = Annotated[Pipeline, Depends(get_pipeline)]
