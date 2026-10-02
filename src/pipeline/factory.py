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


def _answerer_has_credentials(settings: Settings) -> bool:
    # Anthropic and OpenAI need an API key; Ollama is a local server with no key to check —
    # same "no stub needed" reasoning as the always-on PII masker, just scoped to one provider.
    if settings.llm_provider == "openai":
        return bool(settings.openai_api_key)
    if settings.llm_provider == "ollama":
        return True
    return bool(settings.anthropic_api_key)


def build_pipeline(settings: Settings) -> Pipeline:
    # Retrieval is real once USE_STUBS=false (needs Milvus + Neo4j reachable, e.g. after
    # `make neo4j` + `make ingest`). The LLM router is Anthropic-only and used whenever
    # ANTHROPIC_API_KEY is configured, independent of USE_STUBS. The DeepAgents answerer's
    # backend is picked by settings.llm_provider (Anthropic/OpenAI/Ollama); it falls back to
    # the stub when that provider has no usable credentials. PII masking is always real:
    # it's local and free, no reason to stub it. CI sets no API key and USE_STUBS defaults
    # true, so it stays fully offline.
    retrievers: list[Retriever] = (
        [StubVectorRetriever(), StubGraphRetriever()] if settings.use_stubs else [MilvusRetriever(), Neo4jRetriever()]
    )
    parser: RequestParser = LangChainRouter(settings) if settings.anthropic_api_key else StubParser()
    answerer: Answerer = DeepAgentAnswerer(settings) if _answerer_has_credentials(settings) else StubAnswerer()
    return Pipeline(
        parser=parser,
        masker=RegexPIIMasker(),
        retrievers=retrievers,
        answerer=answerer,
    )
