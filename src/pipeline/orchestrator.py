import asyncio
import logging
import time
from collections.abc import Awaitable
from typing import TypeVar

from src.clients.langfuse import traced_span
from src.core.errors import GuardrailViolation
from src.guardrails import check_input
from src.pipeline.base import Answerer, PIIMasker, RequestParser, Retriever
from src.pipeline.merge import merge_context
from src.schemas import ChatRequest, ChatResponse, StageTrace

log = logging.getLogger(__name__)
T = TypeVar("T")


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

            try:
                message = await timed("pii", "mask sensitive data", self._masker.mask(req.message))
                plan = await timed("parse", "intent + source selection", self._parser.parse(message))
                selected = [self._retrievers[s] for s in plan.sources if s in self._retrievers]
                results = await timed(
                    "retrieve",
                    "+".join(r.source for r in selected) + " in parallel",
                    asyncio.gather(*(r.retrieve(plan.query) for r in selected)),
                )
                context = merge_context(list(results))
                answer = await timed("answer", "agentic RAG", self._answerer.answer(plan.query, context))
            except Exception:
                root.update(metadata={"session_id": req.session_id, "outcome": "error"})
                raise

            log.info("chat session=%s stages=%d citations=%d", req.session_id, len(trace), len(context))
            root.update(
                input=message,
                output=answer,
                metadata={
                    "session_id": req.session_id,
                    "sources_queried": sorted({c.source_type for c in context}),
                    "intent": plan.intent,
                    "citations_count": len(context),
                    "outcome": "success",
                },
            )
            return ChatResponse(answer=answer, citations=context, trace=trace)
