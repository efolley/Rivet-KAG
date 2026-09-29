from src.config import Settings
from src.guardrails import RegexPIIMasker
from src.pipeline.answering.agent import DeepAgentAnswerer
from src.pipeline.base import Answerer, RequestParser, Retriever
from src.pipeline.orchestrator import Pipeline
from src.pipeline.parsing.router import LangChainRouter
from src.pipeline.retrieval.milvus import MilvusRetriever
from src.pipeline.retrieval.neo4j import Neo4jRetriever
from src.pipeline.stubs import (
    StubAnswerer,
    StubGraphRetriever,
    StubParser,
    StubVectorRetriever,
)


def build_pipeline(settings: Settings) -> Pipeline:
    # Retrieval is real once USE_STUBS=false (needs Milvus + Neo4j reachable, e.g. after
    # `make neo4j` + `make ingest`). The LLM router and the DeepAgents answerer are used
    # whenever an API key is configured, independent of USE_STUBS — they need no local
    # database, just credentials. PII masking is always real: it's local and free, no reason
    # to stub it. CI sets no API key and USE_STUBS defaults true, so it stays fully offline.
    retrievers: list[Retriever] = (
        [StubVectorRetriever(), StubGraphRetriever()] if settings.use_stubs else [MilvusRetriever(), Neo4jRetriever()]
    )
    parser: RequestParser = LangChainRouter(settings) if settings.anthropic_api_key else StubParser()
    answerer: Answerer = DeepAgentAnswerer(settings) if settings.anthropic_api_key else StubAnswerer()
    return Pipeline(
        parser=parser,
        masker=RegexPIIMasker(),
        retrievers=retrievers,
        answerer=answerer,
    )
