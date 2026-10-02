"""Mini test suite for the DeepAgents answerer: extracting text from its Pydantic-structured
output, falling back when that structure can't be trusted, that the schema itself really
validates, and that llm_provider picks the right model backend / credential gate. The agent's
`ainvoke` call is mocked, so no API key or network access is needed.
"""

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from src.config import Settings
from src.pipeline.answering.agent import AgentAnswer, DeepAgentAnswerer, _build_model
from src.pipeline.factory import build_pipeline
from src.schemas import Citation

CONTEXT = [
    Citation(
        id="vec-1",
        source_type="vector",
        title="expense_policy.md",
        snippet="Meals while travelling are capped at 60 EUR per day.",
        score=0.83,
    )
]


class FakeGraph:
    def __init__(self, result: object) -> None:
        self._result = result

    async def ainvoke(self, state: object) -> object:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _answerer(monkeypatch: pytest.MonkeyPatch, result: object) -> DeepAgentAnswerer:
    answerer = DeepAgentAnswerer(Settings(anthropic_api_key="sk-ant-fake-test-key"))
    monkeypatch.setattr(answerer, "_agent", FakeGraph(result))
    return answerer


async def test_agent_extracts_text_from_structured_response(monkeypatch: pytest.MonkeyPatch) -> None:
    decision = AgentAnswer(answer="Meals are capped at 60 EUR per day.", citation_ids=["vec-1"], confidence="high")
    answerer = _answerer(monkeypatch, {"structured_response": decision})

    result = await answerer.answer("What is the meal limit?", CONTEXT)

    assert result == "Meals are capped at 60 EUR per day."


BAD_TYPE_RESULT = {"structured_response": {"answer": "oops", "citation_ids": [], "confidence": "high"}}


@pytest.mark.parametrize(
    ("fake_result", "context", "expected_substring"),
    [
        pytest.param(TimeoutError("timed out"), CONTEXT, "expense_policy.md", id="llm-call-fails-with-context"),
        pytest.param(TimeoutError("timed out"), [], "couldn't find anything", id="llm-call-fails-no-context"),
        pytest.param(BAD_TYPE_RESULT, CONTEXT, "expense_policy.md", id="wrong-structured-response-type"),
    ],
)
async def test_agent_falls_back_to_context_on_failure(
    monkeypatch: pytest.MonkeyPatch, fake_result: object, context: list[Citation], expected_substring: str
) -> None:
    answerer = _answerer(monkeypatch, fake_result)

    result = await answerer.answer("What is the meal limit?", context)

    assert expected_substring in result


def test_agent_answer_schema_rejects_an_invalid_confidence_value() -> None:
    with pytest.raises(ValidationError):
        AgentAnswer(answer="x", citation_ids=[], confidence="very high")


def test_factory_selects_deep_agent_answerer_only_with_api_key() -> None:
    without_key = build_pipeline(Settings(anthropic_api_key=""))
    with_key = build_pipeline(Settings(anthropic_api_key="sk-ant-fake-test-key"))

    assert type(without_key._answerer).__name__ == "StubAnswerer"
    assert type(with_key._answerer).__name__ == "DeepAgentAnswerer"


@pytest.mark.parametrize(
    ("provider", "expected_type"),
    [
        ("anthropic", ChatAnthropic),
        ("openai", ChatOpenAI),
        ("ollama", ChatOllama),
    ],
)
def test_build_model_picks_backend_from_llm_provider(provider: str, expected_type: type) -> None:
    settings = Settings(
        llm_provider=provider,  # type: ignore[arg-type]
        anthropic_api_key="sk-ant-fake-test-key",
        openai_api_key="sk-fake-test-key",
    )
    assert isinstance(_build_model(settings), expected_type)


def test_factory_falls_back_to_stub_for_openai_without_a_key() -> None:
    without_key = build_pipeline(Settings(llm_provider="openai", openai_api_key=""))
    with_key = build_pipeline(Settings(llm_provider="openai", openai_api_key="sk-fake-test-key"))

    assert type(without_key._answerer).__name__ == "StubAnswerer"
    assert type(with_key._answerer).__name__ == "DeepAgentAnswerer"


def test_factory_uses_real_answerer_for_ollama_with_no_key_needed() -> None:
    pipeline = build_pipeline(Settings(llm_provider="ollama"))
    assert type(pipeline._answerer).__name__ == "DeepAgentAnswerer"
