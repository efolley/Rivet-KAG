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
    # ids of any DataEditProposal rows the agent created this turn (see README's "Agent
    # actions") -- always empty unless the answerer was built with enable_actions=True. Nothing
    # in Milvus/Neo4j has changed yet; these are pending, surfaced so the UI can point the user
    # at them for review.
    proposed_action_ids: list[int] = field(default_factory=list)


class Answerer(Protocol):
    async def answer(
        self,
        query: str,
        context: list[Citation],
        max_cost_usd: float | None = None,
        session_id: str = "unknown",
    ) -> AnswerResult:
        """`max_cost_usd` overrides the stage's own default pre-flight budget
        (`pricing.ANSWER_BUDGET_USD`) for this one call; `None` means "use the default". Lets a
        caller that already knows this request must stay free (e.g. a session over its daily
        cap -- see src/api/routes/chat.py) force the existing budget-rejection fallback path by
        passing `0.0`, rather than duplicating that fallback logic.

        `session_id` is threaded through only so a real answerer with actions enabled can
        attribute any proposal it creates to the right chat session (see
        src/pipeline/answering/tools.py); StubAnswerer ignores it."""
        ...
