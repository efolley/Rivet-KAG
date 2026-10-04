"""LLM-based request parser and router.

Classifies the user's question and decides which retrievers to query: the vector store, the
knowledge graph, or both. This is the "router" stage of the pipeline — it does not answer the
question or rewrite it, only decides where to look. Requires ANTHROPIC_API_KEY; the factory
falls back to StubParser (always query both sources) when no key is configured, and this class
falls back the same way if a call fails, so one bad LLM response never breaks a chat request.
"""

import logging

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field, SecretStr

from src.config import Settings
from src.pipeline.base import Plan
from src.pipeline.pricing import cost_usd, usage_from_ai_message
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
        self._model_name = settings.llm_model
        llm = ChatAnthropic(
            model_name=settings.llm_model,
            api_key=SecretStr(settings.anthropic_api_key),
            temperature=0,
            max_tokens_to_sample=256,
            timeout=10,
            stop=None,
        )
        # include_raw=True trades the plain RouterDecision return for {"raw", "parsed",
        # "parsing_error"} -- "raw" is the underlying AIMessage, needed for cost accounting
        # (usage_metadata isn't available once with_structured_output extracts just the schema).
        self._router = llm.with_structured_output(RouterDecision, include_raw=True)

    async def parse(self, message: str) -> Plan:
        try:
            result = await self._router.ainvoke([SystemMessage(SYSTEM_PROMPT), HumanMessage(message)])
            if not isinstance(result, dict):
                raise TypeError(f"unexpected router output type: {type(result)!r}")
            parsed = result.get("parsed")
            if not isinstance(parsed, RouterDecision):
                raise TypeError(f"unexpected router output type: {type(parsed)!r}")
        except Exception:
            log.exception("LLM router failed; falling back to querying both sources")
            return Plan(intent="question_answering", query=message, sources=BOTH_SOURCES)

        raw = result.get("raw")
        usage = usage_from_ai_message(raw) if isinstance(raw, AIMessage) else None
        return Plan(
            intent=parsed.intent,
            query=message,
            sources=parsed.sources or BOTH_SOURCES,
            model=self._model_name,
            usage=usage,
            cost_usd=cost_usd(self._model_name, usage) if usage is not None else None,
        )
