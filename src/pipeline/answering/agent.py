"""DeepAgents-based answerer: synthesizes a grounded answer from retrieved context, with
Pydantic-structured output (the answer text, which citations were used, and a confidence
rating). Requires ANTHROPIC_API_KEY; the factory falls back to StubAnswerer without one, and
this class falls back the same way if a call fails, so a bad LLM response never breaks a chat
request — the citations found by retrieval are still shown even if synthesis fails.
"""

import logging
from typing import Literal

from deepagents import create_deep_agent
from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel, Field, SecretStr

from src.config import Settings
from src.schemas import Citation

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a knowledge assistant. Answer the user's question using only the \
context items given below — each is labelled with an id and comes from either a vector \
document search or a knowledge graph lookup.

Rules:
- Answer only from the given context. If the context doesn't contain the answer, say so \
plainly instead of guessing.
- In `citation_ids`, list the ids of every context item you actually relied on. Never invent \
an id that isn't in the context.
- Set `confidence` to "low" if the context only partially covers the question, or "high" if \
it clearly answers it."""


class AgentAnswer(BaseModel):
    answer: str = Field(description="the final answer to the user's question, grounded only in the provided context")
    citation_ids: list[str] = Field(description="ids of the context items that directly support the answer")
    confidence: Literal["high", "medium", "low"] = Field(description="how well the context supports this answer")


def _format_context(context: list[Citation]) -> str:
    if not context:
        return "(no context was retrieved for this question)"
    return "\n\n".join(f"[{c.id}] ({c.source_type}) {c.title}\n{c.snippet}" for c in context)


def _fallback_answer(context: list[Citation]) -> str:
    if not context:
        return "I couldn't find anything relevant to answer that question."
    return "I found some relevant information but could not generate a full answer:\n\n" + _format_context(context)


class DeepAgentAnswerer:
    def __init__(self, settings: Settings) -> None:
        model = ChatAnthropic(
            model_name=settings.llm_model,
            api_key=SecretStr(settings.anthropic_api_key),
            temperature=0,
            max_tokens_to_sample=1024,
            timeout=30,
            stop=None,
        )
        self._agent = create_deep_agent(model=model, system_prompt=SYSTEM_PROMPT, response_format=AgentAnswer)

    async def answer(self, query: str, context: list[Citation]) -> str:
        prompt = f"Question: {query}\n\nContext:\n{_format_context(context)}"
        try:
            result = await self._agent.ainvoke({"messages": [{"role": "user", "content": prompt}]})
            structured = result["structured_response"]
            if not isinstance(structured, AgentAnswer):
                raise TypeError(f"unexpected agent output type: {type(structured)!r}")
        except Exception:
            log.exception("DeepAgents answerer failed; falling back to a context-only summary")
            return _fallback_answer(context)
        log.info("agent answered confidence=%s citations=%s", structured.confidence, structured.citation_ids)
        return structured.answer
