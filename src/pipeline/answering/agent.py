"""DeepAgents-based answerer: synthesizes a grounded answer from retrieved context, with
Pydantic-structured output (the answer text, which citations were used, and a confidence
rating). `settings.llm_provider` picks the model backend (Anthropic, OpenAI or a local Ollama
server); the factory falls back to StubAnswerer when the selected provider has no usable
credentials, and this class falls back the same way if a call fails, so a bad LLM response
never breaks a chat request — the citations found by retrieval are still shown even if
synthesis fails.
"""

import asyncio
import logging
from typing import Literal, cast

from deepagents import create_deep_agent
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.messages.content import TextContentBlock
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, SecretStr

from src.config import Settings
from src.pipeline.base import AnswerResult
from src.pipeline.pricing import ANSWER_BUDGET_USD, TokenUsage, cost_usd, usage_from_ai_message
from src.schemas import Citation

log = logging.getLogger(__name__)

MAX_OUTPUT_TOKENS = 1024

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


def _sum_usage(result: object) -> TokenUsage | None:
    """DeepAgents can make several LLM round-trips per request (tool calls, retries); sum
    usage across every AIMessage in the run so the stage's cost reflects the whole call, not
    just the last turn. None when there's nothing to sum (e.g. the call never reached the
    model)."""
    if not isinstance(result, dict):
        return None
    messages = result.get("messages")
    if not isinstance(messages, list):
        return None
    total = TokenUsage()
    found = False
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.usage_metadata:
            found = True
            u = usage_from_ai_message(msg)
            total.input_tokens += u.input_tokens
            total.output_tokens += u.output_tokens
            total.cache_read_tokens += u.cache_read_tokens
            total.cache_creation_tokens += u.cache_creation_tokens
    return total if found else None


def _fallback_answer(context: list[Citation]) -> str:
    if not context:
        return "I couldn't find anything relevant to answer that question."
    # Plain, human-readable text only -- the raw retrieved context is shown separately
    # (the chat UI's own "Context" section), so it shouldn't be duplicated into the answer.
    return (
        "I found relevant information but couldn't generate a complete answer. "
        "See the sources below for the details."
    )


def _build_system_prompt(settings: Settings) -> str | SystemMessage:
    """Prompt caching (`cache_control: {"type": "ephemeral"}`) is an Anthropic-specific
    mechanism -- OpenAI caches automatically with no API to opt in, and Ollama has no concept of
    it -- so only the Anthropic path gets a SystemMessage with a cache breakpoint; other
    providers get the plain string. `create_deep_agent` preserves a SystemMessage's content
    blocks and appends its own boilerplate as a further block, so the breakpoint still covers
    the whole of SYSTEM_PROMPT (the large, stable part) as a cached prefix. Tool-schema caching
    (the other half of this roadmap item) isn't implemented: DeepAgents builds its own built-in
    tool list internally and doesn't expose a hook to attach cache_control to it."""
    if settings.llm_provider != "anthropic":
        return SYSTEM_PROMPT
    # langchain_anthropic's text-block formatter (_format_text_block) reads cache_control only
    # as a bare top-level key -- it does NOT fall back to TextContentBlock's typed `extras`
    # escape hatch for this particular block type (verified by inspecting the formatted output
    # directly; `extras` silently dropped cache_control instead of carrying it through). That
    # key isn't part of TextContentBlock's declared shape, hence the cast.
    block = cast(
        TextContentBlock, {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
    )
    return SystemMessage(content_blocks=[block])


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
        self._model_name = settings.llm_model
        self._model = _build_model(settings)
        self._agent = create_deep_agent(
            model=self._model, system_prompt=_build_system_prompt(settings), response_format=AgentAnswer
        )

    async def _estimate_cost_usd(self, prompt: str) -> float | None:
        """Pre-flight estimate before the real call: input tokens via the model's own
        get_num_tokens_from_messages (Anthropic's is backed by the real messages.count_tokens
        API; OpenAI's is a local tiktoken count; Ollama's is a cheap local heuristic -- each
        model picks the best it has), plus a worst-case output cost at the configured output
        cap. None means the model's price isn't in the catalog, so no budget verdict is possible
        -- callers must not block as a side effect of unknown pricing."""
        messages: list[BaseMessage] = [HumanMessage(content=prompt)]
        try:
            input_tokens = await asyncio.to_thread(self._model.get_num_tokens_from_messages, messages)
        except Exception:
            log.warning("Pre-flight token count failed for %s; skipping the budget check", self._model_name)
            return None
        worst_case = TokenUsage(input_tokens=input_tokens, output_tokens=MAX_OUTPUT_TOKENS)
        return cost_usd(self._model_name, worst_case)

    async def answer(self, query: str, context: list[Citation]) -> AnswerResult:
        prompt = f"Question: {query}\n\nContext:\n{_format_context(context)}"

        estimated_cost = await self._estimate_cost_usd(prompt)
        if estimated_cost is not None and estimated_cost > ANSWER_BUDGET_USD:
            log.warning(
                "Pre-flight estimate $%.4f exceeds the $%.2f answer budget for %s; skipping the LLM call",
                estimated_cost,
                ANSWER_BUDGET_USD,
                self._model_name,
            )
            return AnswerResult(
                text=_fallback_answer(context),
                model=self._model_name,
                usage=TokenUsage(),
                cost_usd=0.0,
                budget_rejected=True,
            )

        try:
            result = await self._agent.ainvoke({"messages": [{"role": "user", "content": prompt}]})
        except Exception:
            log.exception("DeepAgents answerer call failed; falling back to a context-only summary")
            return AnswerResult(text=_fallback_answer(context), model=self._model_name)

        usage = _sum_usage(result)
        cost = cost_usd(self._model_name, usage) if usage is not None else None

        structured = result.get("structured_response") if isinstance(result, dict) else None
        if isinstance(structured, AgentAnswer):
            log.info("agent answered confidence=%s citations=%s", structured.confidence, structured.citation_ids)
            return AnswerResult(text=structured.answer, model=self._model_name, usage=usage, cost_usd=cost)

        text = _last_plain_text_answer(result)
        if text:
            log.warning("structured_response missing; using the agent's final plain-text message instead")
            return AnswerResult(text=text, model=self._model_name, usage=usage, cost_usd=cost)

        log.error("DeepAgents answerer returned no usable output; falling back to a context-only summary")
        return AnswerResult(text=_fallback_answer(context), model=self._model_name, usage=usage, cost_usd=cost)
