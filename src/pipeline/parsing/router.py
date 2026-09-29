"""LLM-based request parser and router.

Classifies the user's question and decides which retrievers to query: the vector store, the
knowledge graph, or both. This is the "router" stage of the pipeline — it does not answer the
question or rewrite it, only decides where to look. Requires ANTHROPIC_API_KEY; the factory
falls back to StubParser (always query both sources) when no key is configured, and this class
falls back the same way if a call fails, so one bad LLM response never breaks a chat request.
"""

import logging

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, SecretStr

from src.config import Settings
from src.pipeline.base import Plan
from src.schemas import SourceType

log = logging.getLogger(__name__)

BOTH_SOURCES: list[SourceType] = ["vector", "graph"]

SYSTEM_PROMPT = """You are the router for a knowledge assistant with two data sources:

- vector: semantic search over company documents (policies, runbooks, handbooks, an FAQ). \
Good for "what does the policy say", "how do I...", "what is the process for...".
- graph: a knowledge graph of employees, teams, projects, tools and documents, and how they \
relate (who leads/works on/owns what). Good for "who...", "which team...", "what does X use".

Given the user's question, decide which source(s) are needed to answer it well. Pick both when \
the question needs both an entity lookup and document content, e.g. "who owns the VPN policy \
and what does it say". Always pick at least one source."""


class RouterDecision(BaseModel):
    intent: str = Field(description="a short phrase describing what the user wants, e.g. 'find a policy answer'")
    sources: list[SourceType] = Field(description="one or both of 'vector', 'graph'; never empty")


class LangChainRouter:
    def __init__(self, settings: Settings) -> None:
        llm = ChatAnthropic(
            model_name=settings.llm_model,
            api_key=SecretStr(settings.anthropic_api_key),
            temperature=0,
            max_tokens_to_sample=256,
            timeout=10,
            stop=None,
        )
        self._router = llm.with_structured_output(RouterDecision)

    async def parse(self, message: str) -> Plan:
        try:
            result = await self._router.ainvoke([SystemMessage(SYSTEM_PROMPT), HumanMessage(message)])
            if not isinstance(result, RouterDecision):
                raise TypeError(f"unexpected router output type: {type(result)!r}")
        except Exception:
            log.exception("LLM router failed; falling back to querying both sources")
            return Plan(intent="question_answering", query=message, sources=BOTH_SOURCES)
        return Plan(intent=result.intent, query=message, sources=result.sources or BOTH_SOURCES)
