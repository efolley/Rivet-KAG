"""DeepAgents-based answerer: synthesizes a grounded answer from retrieved context, with
Pydantic-structured output (the answer text, which citations were used, and a confidence
rating). `settings.llm_provider` picks the model backend (Anthropic, OpenAI or a local Ollama
server); the factory falls back to StubAnswerer when the selected provider has no usable
credentials, and this class falls back the same way if a call fails, so a bad LLM response
never breaks a chat request — the citations found by retrieval are still shown even if
synthesis fails.
"""

import asyncio
import json
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
from src.pipeline.answering.tools import ACTION_TOOLS, current_session_id, proposed_ids
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

ACTIONS_ADDENDUM = """

You also have tools to propose a change to a vector document chunk or a graph node property \
(propose_vector_chunk_update, propose_graph_property_update). These tools NEVER apply a change \
immediately -- they only record a pending proposal for a human to review and approve. Only use \
them when the user explicitly asks you to change, correct, update or fix something in the data; \
never propose a change just because you noticed something that looks wrong. Always state clearly \
in your answer that the change is pending human approval, not yet applied."""


class AgentAnswer(BaseModel):
    answer: str = Field(description="the final answer to the user's question, grounded only in the provided context")
    citation_ids: list[str] = Field(description="ids of the context items that directly support the answer")
    confidence: Literal["high", "medium", "low"] = Field(description="how well the context supports this answer")


def _format_context(context: list[Citation]) -> str:
    if not context:
        return "(no context was retrieved for this question)"
    return "\n\n".join(f"[{c.id}] ({c.source_type}) {c.title}\n{c.snippet}" for c in context)


def _extract_answer_from_tool_call_text(content: str) -> str | None:
    """Some models (small local Ollama models especially) print the `AgentAnswer` tool call
    as plain text instead of actually invoking it -- e.g. `{"name": "AgentAnswer",
    "arguments": {"answer": "...", ...}}`. Recover the real `answer` field from that JSON
    rather than show the raw blob to the user (this was a real bug, caught live: the chat UI
    displayed the literal JSON as the answer). Returns None for text that isn't
    AgentAnswer-tool-call-shaped JSON -- the caller treats that as "not recoverable" rather
    than falling through to showing it verbatim, since anything that parses as an object but
    doesn't match is far more likely to be a malformed tool call than a genuine prose answer."""
    if not (content.startswith("{") and content.endswith("}")):
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    arguments = parsed.get("arguments")
    if isinstance(arguments, dict):
        nested_answer = arguments.get("answer")
        if isinstance(nested_answer, str):
            return nested_answer
    top_level_answer = parsed.get("answer")
    if isinstance(top_level_answer, str):
        return top_level_answer
    return None


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
            content = msg.content.strip()
            recovered = _extract_answer_from_tool_call_text(content)
            if recovered is not None:
                return recovered
            if content.startswith("{"):
                # Looks like a tool-call attempt that didn't match the expected shape -- not
                # recoverable, and definitely not something to show the user verbatim (see
                # _extract_answer_from_tool_call_text). Let the caller fall back instead.
                return None
            return content
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


def _build_system_prompt(settings: Settings, enable_actions: bool = False) -> str | SystemMessage:
    """Prompt caching (`cache_control: {"type": "ephemeral"}`) is an Anthropic-specific
    mechanism -- OpenAI caches automatically with no API to opt in, and Ollama has no concept of
    it -- so only the Anthropic path gets a SystemMessage with a cache breakpoint; other
    providers get the plain string. `create_deep_agent` preserves a SystemMessage's content
    blocks and appends its own boilerplate as a further block, so the breakpoint still covers
    the whole of SYSTEM_PROMPT (the large, stable part) as a cached prefix. Tool-schema caching
    (the other half of this roadmap item) isn't implemented: DeepAgents builds its own built-in
    tool list internally and doesn't expose a hook to attach cache_control to it."""
    text = SYSTEM_PROMPT + ACTIONS_ADDENDUM if enable_actions else SYSTEM_PROMPT
    if settings.llm_provider != "anthropic":
        return text
    # langchain_anthropic's text-block formatter (_format_text_block) reads cache_control only
    # as a bare top-level key -- it does NOT fall back to TextContentBlock's typed `extras`
    # escape hatch for this particular block type (verified by inspecting the formatted output
    # directly; `extras` silently dropped cache_control instead of carrying it through). That
    # key isn't part of TextContentBlock's declared shape, hence the cast.
    block = cast(TextContentBlock, {"type": "text", "text": text, "cache_control": {"type": "ephemeral"}})
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
    def __init__(self, settings: Settings, enable_actions: bool = False) -> None:
        self._model_name = settings.llm_model
        self._model = _build_model(settings)
        self._agent = create_deep_agent(
            model=self._model,
            tools=ACTION_TOOLS if enable_actions else [],
            system_prompt=_build_system_prompt(settings, enable_actions),
            response_format=AgentAnswer,
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

    async def answer(
        self,
        query: str,
        context: list[Citation],
        max_cost_usd: float | None = None,
        session_id: str = "unknown",
    ) -> AnswerResult:
        prompt = f"Question: {query}\n\nContext:\n{_format_context(context)}"
        budget = ANSWER_BUDGET_USD if max_cost_usd is None else max_cost_usd

        # budget <= 0 means the caller already decided this request must not spend anything
        # (e.g. a session over its daily cap -- see src/api/routes/chat.py's SESSION_DAILY_BUDGET_USD
        # check). Skip the pre-flight token count entirely in that case: there's no estimate
        # that could change the outcome, and a failed/unknown estimate must not accidentally let
        # a zero-budget request through.
        estimated_cost = None if budget <= 0 else await self._estimate_cost_usd(prompt)
        if budget <= 0 or (estimated_cost is not None and estimated_cost > budget):
            log.warning(
                "Pre-flight estimate $%s exceeds the $%.4f answer budget for %s; skipping the LLM call",
                f"{estimated_cost:.4f}" if estimated_cost is not None else "n/a",
                budget,
                self._model_name,
            )
            return AnswerResult(
                text=_fallback_answer(context),
                model=self._model_name,
                usage=TokenUsage(),
                cost_usd=0.0,
                budget_rejected=True,
            )

        # Ambient, per-call context for any action tool invoked during this agent run (see
        # src/pipeline/answering/tools.py) -- a tool reads session_id from here rather than the
        # model supplying it as an argument, and appends any proposal id it creates to the same
        # list we read back below. Harmless when enable_actions=False: the tools simply aren't
        # bound to the agent, so they're never called and the list stays empty.
        session_token = current_session_id.set(session_id)
        ids_token = proposed_ids.set([])
        try:
            result = await self._agent.ainvoke({"messages": [{"role": "user", "content": prompt}]})
        except Exception:
            log.exception("DeepAgents answerer call failed; falling back to a context-only summary")
            return AnswerResult(
                text=_fallback_answer(context), model=self._model_name, proposed_action_ids=proposed_ids.get()
            )
        finally:
            proposed = proposed_ids.get()
            current_session_id.reset(session_token)
            proposed_ids.reset(ids_token)

        usage = _sum_usage(result)
        cost = cost_usd(self._model_name, usage) if usage is not None else None

        structured = result.get("structured_response") if isinstance(result, dict) else None
        if isinstance(structured, AgentAnswer):
            log.info("agent answered confidence=%s citations=%s", structured.confidence, structured.citation_ids)
            return AnswerResult(
                text=structured.answer, model=self._model_name, usage=usage, cost_usd=cost, proposed_action_ids=proposed
            )

        text = _last_plain_text_answer(result)
        if text:
            log.warning("structured_response missing; using the agent's final plain-text message instead")
            return AnswerResult(
                text=text, model=self._model_name, usage=usage, cost_usd=cost, proposed_action_ids=proposed
            )

        log.error("DeepAgents answerer returned no usable output; falling back to a context-only summary")
        return AnswerResult(
            text=_fallback_answer(context),
            model=self._model_name,
            usage=usage,
            cost_usd=cost,
            proposed_action_ids=proposed,
        )
