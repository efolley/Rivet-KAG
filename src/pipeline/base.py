"""Interfaces for each pipeline stage. Real implementations (LangChain, Milvus, Neo4j, DeepAgents) plug in here."""

from dataclasses import dataclass, field
from typing import Protocol

from src.pipeline.pricing import TokenUsage
from src.schemas import Citation, SourceType


@dataclass
class Plan:
    intent: str
    query: str
    sources: list[SourceType] = field(default_factory=lambda: ["vector", "graph"])
    # Cost accounting, filled in by real (LLM-backed) parsers; stays None for StubParser, which
    # makes no LLM call and so has no usage/cost to report -- not $0.00, genuinely unknown/n/a.
    model: str | None = None
    usage: TokenUsage | None = None
    cost_usd: float | None = None


class RequestParser(Protocol):
    async def parse(self, message: str) -> Plan: ...


class PIIMasker(Protocol):
    async def mask(self, text: str) -> str: ...


class Retriever(Protocol):
    source: SourceType

    async def retrieve(self, query: str) -> list[Citation]: ...


@dataclass
class AnswerResult:
    text: str
    # Same cost-accounting convention as Plan above: None for StubAnswerer, filled in by
    # DeepAgentAnswerer. budget_rejected marks the pre-flight-count_tokens fallback path (see
    # DeepAgentAnswerer.answer) -- a real LLM call was skipped, so usage/cost are 0, not unknown.
    model: str | None = None
    usage: TokenUsage | None = None
    cost_usd: float | None = None
    budget_rejected: bool = False


class Answerer(Protocol):
    async def answer(self, query: str, context: list[Citation]) -> AnswerResult: ...
