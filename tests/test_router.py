"""Mini test suite for the LLM router: mapping a decision to a Plan, and falling back to
querying both sources whenever the LLM call can't be trusted. The LLM call itself
(`self._router.ainvoke`) is mocked, so no ANTHROPIC_API_KEY or network access is needed.
"""

from collections.abc import Awaitable, Callable

import pytest

from src.config import Settings
from src.pipeline.factory import build_pipeline
from src.pipeline.parsing.router import LangChainRouter, RouterDecision


class FakeRunnable:
    def __init__(self, ainvoke: Callable[[object], Awaitable[object]]) -> None:
        self._ainvoke = ainvoke

    async def ainvoke(self, messages: object) -> object:
        return await self._ainvoke(messages)


def _router(monkeypatch: pytest.MonkeyPatch, ainvoke: Callable[[object], Awaitable[object]]) -> LangChainRouter:
    router = LangChainRouter(Settings(anthropic_api_key="sk-ant-fake-test-key"))
    monkeypatch.setattr(router, "_router", FakeRunnable(ainvoke))
    return router


async def test_router_parses_decision_into_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_ainvoke(messages: object) -> object:
        return RouterDecision(intent="find a policy answer", sources=["vector"])

    plan = await _router(monkeypatch, fake_ainvoke).parse("What is the meal expense limit?")

    assert plan.intent == "find a policy answer"
    assert plan.sources == ["vector"]
    assert plan.query == "What is the meal expense limit?"  # the router classifies, it doesn't rewrite


async def _raises(messages: object) -> object:
    raise TimeoutError("anthropic request timed out")


async def _returns_wrong_type(messages: object) -> object:
    return {"intent": "oops", "sources": ["vector"]}  # not a RouterDecision


async def _returns_empty_sources(messages: object) -> object:
    return RouterDecision(intent="unclear", sources=[])


@pytest.mark.parametrize("fake_ainvoke", [_raises, _returns_wrong_type, _returns_empty_sources])
async def test_router_falls_back_to_both_sources_on_failure(
    monkeypatch: pytest.MonkeyPatch, fake_ainvoke: Callable[[object], Awaitable[object]]
) -> None:
    plan = await _router(monkeypatch, fake_ainvoke).parse("Who leads the Data Platform team?")

    assert plan.sources == ["vector", "graph"]
    assert plan.query == "Who leads the Data Platform team?"


def test_factory_selects_langchain_router_only_with_api_key() -> None:
    without_key = build_pipeline(Settings(anthropic_api_key=""))
    with_key = build_pipeline(Settings(anthropic_api_key="sk-ant-fake-test-key"))

    assert type(without_key._parser).__name__ == "StubParser"
    assert type(with_key._parser).__name__ == "LangChainRouter"
