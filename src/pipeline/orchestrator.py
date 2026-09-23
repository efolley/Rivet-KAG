import asyncio
import logging
import time
from collections.abc import Awaitable
from typing import TypeVar

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
        check_input(req.message)
        trace: list[StageTrace] = []

        async def timed(name: str, detail: str, coro: Awaitable[T]) -> T:
            start = time.perf_counter()
            result = await coro
            ms = round((time.perf_counter() - start) * 1000, 1)
            trace.append(StageTrace(name=name, detail=detail, duration_ms=ms))
            return result

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
        log.info("chat session=%s stages=%d citations=%d", req.session_id, len(trace), len(context))
        return ChatResponse(answer=answer, citations=context, trace=trace)
