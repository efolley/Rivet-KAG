from src.config import Settings
from src.pipeline.orchestrator import Pipeline
from src.pipeline.stubs import (
    StubAnswerer,
    StubGraphRetriever,
    StubParser,
    StubPIIMasker,
    StubVectorRetriever,
)


def build_pipeline(settings: Settings) -> Pipeline:
    if not settings.use_stubs:
        raise NotImplementedError("Real pipeline components are not implemented yet; set USE_STUBS=true.")
    return Pipeline(
        parser=StubParser(),
        masker=StubPIIMasker(),
        retrievers=[StubVectorRetriever(), StubGraphRetriever()],
        answerer=StubAnswerer(),
    )
