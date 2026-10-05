"""Stub stage implementations so the API works end-to-end before real integrations land."""

import asyncio

from src.pipeline.base import AnswerResult, Plan
from src.schemas import Citation, SourceType


class StubParser:
    async def parse(self, message: str) -> Plan:  # TODO(langchain): LLM intent + source selection
        return Plan(intent="question_answering", query=message)


class StubVectorRetriever:
    source: SourceType = "vector"

    async def retrieve(self, query: str) -> list[Citation]:  # TODO(milvus): embed + ANN search
        await asyncio.sleep(0.05)
        return [
            Citation(
                id="vec-1",
                source_type="vector",
                title="onboarding_guide.md",
                snippet="New employees receive laptop access on day one and VPN access after security training.",
                score=0.87,
            )
        ]


class StubGraphRetriever:
    source: SourceType = "graph"

    async def retrieve(self, query: str) -> list[Citation]:  # TODO(neo4j): generate + run Cypher
        await asyncio.sleep(0.05)
        return [
            Citation(
                id="graph-1",
                source_type="graph",
                title="(Employee)-[:MEMBER_OF]->(Team)",
                snippet="MATCH (e:Employee)-[:MEMBER_OF]->(t:Team) RETURN e.name, t.name LIMIT 5",
            )
        ]


class StubAnswerer:
    """Used when no ANTHROPIC_API_KEY is set; see pipeline.answering.agent.DeepAgentAnswerer."""

    async def answer(
        self,
        query: str,
        context: list[Citation],
        max_cost_usd: float | None = None,
        session_id: str = "unknown",
    ) -> AnswerResult:
        text = (
            f'[stub answer] You asked: "{query}". Found {len(context)} context items. '
            "Set ANTHROPIC_API_KEY to get a real, generated answer."
        )
        return AnswerResult(text=text)
