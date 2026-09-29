"""Mini test suite for the DeepAgents answerer: extracting text from its Pydantic-structured
output, falling back when that structure can't be trusted, and that the schema itself really
validates. The agent's `ainvoke` call is mocked, so no ANTHROPIC_API_KEY or network access is
needed.
"""

import pytest
from pydantic import ValidationError

from src.config import Settings
from src.pipeline.answering.agent import AgentAnswer, DeepAgentAnswerer
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
