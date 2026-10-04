import asyncio
import logging
import time
from collections.abc import Awaitable
from typing import Protocol, TypeVar

from src.clients.langfuse import traced_span
from src.core.errors import GuardrailViolation
from src.guardrails import check_input
from src.pipeline.base import Answerer, PIIMasker, RequestParser, Retriever
from src.pipeline.merge import merge_context
from src.pipeline.pricing import TOTAL_BUDGET_USD, TokenUsage
from src.schemas import ChatRequest, ChatResponse, StageTrace

log = logging.getLogger(__name__)
T = TypeVar("T")


class _CostAware(Protocol):
    """Shared shape of Plan and AnswerResult (src/pipeline/base.py) -- both carry the same
    cost-accounting fields, so one helper (`timed_llm` below) can record either."""

    model: str | None
    usage: TokenUsage | None
    cost_usd: float | None


TCost = TypeVar("TCost", bound=_CostAware)


class Pipeline:
    def __init__(
        self,
        parser: RequestParser,
        masker: PIIMasker,
        retrievers: list[Retriever],
        answerer: Answerer,
    ) -> None:
        self._parser = parser
        self._masker = masker
        self._retrievers = {r.source: r for r in retrievers}
        self._answerer = answerer

    async def run(self, req: ChatRequest) -> ChatResponse:
        # Per-request/per-stage Langfuse tracing (local only -- see src/clients/langfuse.py).
        # The root span's `input` is set only after the "pii" stage below, never from
        # req.message directly: question_raw must never reach the trace, matching the
        # question_raw-is-never-persisted rule already followed for the Postgres audit log.
        with traced_span("chat", as_type="chain", metadata={"session_id": req.session_id}) as root:
            try:
                check_input(req.message)
            except GuardrailViolation:
                root.update(metadata={"session_id": req.session_id, "outcome": "guardrail_blocked"})
                raise

            trace: list[StageTrace] = []

            async def timed(name: str, detail: str, coro: Awaitable[T]) -> T:
                start = time.perf_counter()
                with traced_span(name, metadata={"detail": detail}) as span:
                    result = await coro
                    ms = round((time.perf_counter() - start) * 1000, 1)
                    span.update(output={"duration_ms": ms})
                trace.append(StageTrace(name=name, detail=detail, duration_ms=ms))
                return result

            async def timed_llm(name: str, detail: str, coro: Awaitable[TCost]) -> TCost:
                # Per-stage cost accounting (see src/pipeline/pricing.py): parse and answer are
                # the only stages that call an LLM, so they're the only ones with token/cost
                # fields to report -- pii/retrieve stay on the plain `timed` helper above.
                start = time.perf_counter()
                with traced_span(name, metadata={"detail": detail}) as span:
                    result = await coro
                    ms = round((time.perf_counter() - start) * 1000, 1)
                    span.update(
                        output={"duration_ms": ms, "cost_usd": result.cost_usd},
                        metadata={"model": result.model, "budget_rejected": getattr(result, "budget_rejected", False)},
                    )
                trace.append(
                    StageTrace(
                        name=name,
                        detail=detail,
                        duration_ms=ms,
                        model=result.model,
                        input_tokens=result.usage.input_tokens if result.usage else None,
                        output_tokens=result.usage.output_tokens if result.usage else None,
                        cost_usd=result.cost_usd,
                        budget_rejected=getattr(result, "budget_rejected", False),
                    )
                )
                return result

            try:
                message = await timed("pii", "mask sensitive data", self._masker.mask(req.message))
                plan = await timed_llm("parse", "intent + source selection", self._parser.parse(message))
                selected = [self._retrievers[s] for s in plan.sources if s in self._retrievers]
                results = await timed(
                    "retrieve",
                    "+".join(r.source for r in selected) + " in parallel",
                    asyncio.gather(*(r.retrieve(plan.query) for r in selected)),
                )
                context = merge_context(list(results))
                answer_result = await timed_llm("answer", "agentic RAG", self._answerer.answer(plan.query, context))
            except Exception:
                root.update(metadata={"session_id": req.session_id, "outcome": "error"})
                raise

            total_cost_usd = None
            if plan.cost_usd is not None and answer_result.cost_usd is not None:
                total_cost_usd = round(plan.cost_usd + answer_result.cost_usd, 6)
                if total_cost_usd > TOTAL_BUDGET_USD:
                    log.warning(
                        "chat session=%s cost $%.4f exceeded the $%.2f/inspection budget",
                        req.session_id,
                        total_cost_usd,
                        TOTAL_BUDGET_USD,
                    )

            log.info("chat session=%s stages=%d citations=%d", req.session_id, len(trace), len(context))
            root.update(
                input=message,
                output=answer_result.text,
                metadata={
                    "session_id": req.session_id,
                    "sources_queried": sorted({c.source_type for c in context}),
                    "intent": plan.intent,
                    "citations_count": len(context),
                    "total_cost_usd": total_cost_usd,
                    "outcome": "success",
                },
            )
            return ChatResponse(
                answer=answer_result.text, citations=context, trace=trace, total_cost_usd=total_cost_usd
            )
