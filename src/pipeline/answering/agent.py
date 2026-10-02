"""DeepAgents-based answerer: synthesizes a grounded answer from retrieved context, with
Pydantic-structured output (the answer text, which citations were used, and a confidence
rating). `settings.llm_provider` picks the model backend (Anthropic, OpenAI or a local Ollama
server); the factory falls back to StubAnswerer when the selected provider has no usable
credentials, and this class falls back the same way if a call fails, so a bad LLM response
never breaks a chat request — the citations found by retrieval are still shown even if
synthesis fails.
"""

import logging
from typing import Literal

from deepagents import create_deep_agent
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
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


def _last_plain_text_answer(result: object) -> str | None:
    """Some models (small local Ollama models especially) don't reliably emit the tool call
    DeepAgents needs to populate `structured_response`, even though they do produce a good
    plain-text final answer. Recover that instead of discarding it for the generic fallback."""
    if not isinstance(result, dict):
        return None
    messages = result.get("messages")
    if not isinstance(messages, list):
        return None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and isinstance(msg.content, str) and msg.content.strip():
            return msg.content.strip()
    return None


def _fallback_answer(context: list[Citation]) -> str:
    if not context:
        return "I couldn't find anything relevant to answer that question."
    # Plain, human-readable text only -- the raw retrieved context is shown separately
    # (the chat UI's own "Context" section), so it shouldn't be duplicated into the answer.
    return (
        "I found relevant information but couldn't generate a complete answer. "
        "See the sources below for the details."
    )


def _build_model(settings: Settings) -> ChatAnthropic | ChatOpenAI | ChatOllama:
    if settings.llm_provider == "openai":
        return ChatOpenAI(
            model=settings.llm_model,
            api_key=SecretStr(settings.openai_api_key),
            temperature=0,
            max_completion_tokens=1024,
            timeout=30,
        )
    if settings.llm_provider == "ollama":
        return ChatOllama(
            model=settings.llm_model,
            base_url=settings.ollama_host,
            temperature=0,
            num_predict=1024,
        )
    return ChatAnthropic(
        model_name=settings.llm_model,
        api_key=SecretStr(settings.anthropic_api_key),
        temperature=0,
        max_tokens_to_sample=1024,
        timeout=30,
        stop=None,
    )


class DeepAgentAnswerer:
    def __init__(self, settings: Settings) -> None:
        model = _build_model(settings)
        self._agent = create_deep_agent(model=model, system_prompt=SYSTEM_PROMPT, response_format=AgentAnswer)

    async def answer(self, query: str, context: list[Citation]) -> str:
        prompt = f"Question: {query}\n\nContext:\n{_format_context(context)}"
        try:
            result = await self._agent.ainvoke({"messages": [{"role": "user", "content": prompt}]})
        except Exception:
            log.exception("DeepAgents answerer call failed; falling back to a context-only summary")
            return _fallback_answer(context)

        structured = result.get("structured_response") if isinstance(result, dict) else None
        if isinstance(structured, AgentAnswer):
            log.info("agent answered confidence=%s citations=%s", structured.confidence, structured.citation_ids)
            return structured.answer

        text = _last_plain_text_answer(result)
        if text:
            log.warning("structured_response missing; using the agent's final plain-text message instead")
            return text

        log.error("DeepAgents answerer returned no usable output; falling back to a context-only summary")
        return _fallback_answer(context)
