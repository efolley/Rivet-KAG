"""Mini test suite for the DeepAgents answerer: extracting text from its Pydantic-structured
output, falling back when that structure can't be trusted, that the schema itself really
validates, cost accounting from usage_metadata, the pre-flight budget rejection, and that
llm_provider picks the right model backend / credential gate. The agent's `ainvoke` call is
mocked and the pre-flight token count is monkeypatched to a fixed value, so no API key or
network access is needed -- ChatAnthropic.get_num_tokens_from_messages otherwise makes a real
call to api.anthropic.com's count_tokens endpoint (see src/pipeline/answering/agent.py).
"""

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from src.config import Settings
from src.pipeline.answering.agent import (
    SYSTEM_PROMPT,
    AgentAnswer,
    DeepAgentAnswerer,
    _build_model,
    _build_system_prompt,
)
from src.pipeline.factory import build_pipeline
from src.pipeline.pricing import ANSWER_BUDGET_USD
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


def _answerer(
    monkeypatch: pytest.MonkeyPatch,
    result: object,
    *,
    model: str = "claude-haiku-4-5-20251001",
    preflight_input_tokens: int = 50,
) -> DeepAgentAnswerer:
    answerer = DeepAgentAnswerer(Settings(anthropic_api_key="sk-ant-fake-test-key", llm_model=model))
    monkeypatch.setattr(answerer, "_agent", FakeGraph(result))
    # ChatAnthropic is a pydantic model -- only declared fields can be set on an instance, so
    # the method is patched on the class instead (monkeypatch reverts it after the test).
    monkeypatch.setattr(
        type(answerer._model), "get_num_tokens_from_messages", lambda self, *a, **k: preflight_input_tokens
    )
    return answerer


def _ai_message(content: str, input_tokens: int = 500, output_tokens: int = 50) -> AIMessage:
    return AIMessage(
        content=content,
        usage_metadata={"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": 0},
    )


async def test_agent_extracts_text_from_structured_response(monkeypatch: pytest.MonkeyPatch) -> None:
    decision = AgentAnswer(answer="Meals are capped at 60 EUR per day.", citation_ids=["vec-1"], confidence="high")
    agent_result = {"structured_response": decision, "messages": [_ai_message("")]}
    answerer = _answerer(monkeypatch, agent_result)

    result = await answerer.answer("What is the meal limit?", CONTEXT)

    assert result.text == "Meals are capped at 60 EUR per day."


BAD_TYPE_RESULT = {"structured_response": {"answer": "oops", "citation_ids": [], "confidence": "high"}}


@pytest.mark.parametrize(
    ("fake_result", "context", "expected_substring"),
    [
        pytest.param(
            TimeoutError("timed out"), CONTEXT, "couldn't generate a complete answer", id="llm-call-fails-with-context"
        ),
        pytest.param(TimeoutError("timed out"), [], "couldn't find anything", id="llm-call-fails-no-context"),
        pytest.param(
            BAD_TYPE_RESULT, CONTEXT, "couldn't generate a complete answer", id="wrong-structured-response-type"
        ),
    ],
)
async def test_agent_falls_back_to_context_on_failure(
    monkeypatch: pytest.MonkeyPatch, fake_result: object, context: list[Citation], expected_substring: str
) -> None:
    answerer = _answerer(monkeypatch, fake_result)

    result = await answerer.answer("What is the meal limit?", context)

    assert expected_substring in result.text


async def test_agent_fallback_does_not_dump_raw_context_into_the_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fallback answer must stay pure, human-readable text -- the UI renders raw retrieved
    context separately (its own "Context" section), so dumping citation snippets into the answer
    would duplicate it there."""
    answerer = _answerer(monkeypatch, TimeoutError("timed out"))

    result = await answerer.answer("What is the meal limit?", CONTEXT)

    assert CONTEXT[0].snippet not in result.text
    assert CONTEXT[0].id not in result.text


async def test_agent_uses_final_plain_text_message_when_structured_response_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Small local models (e.g. a 3B Ollama model) often don't emit the tool call DeepAgents
    needs to fill structured_response, even though their final message is a perfectly good
    plain-text answer. That should be used instead of falling all the way back to the generic
    "couldn't generate a complete answer" message."""
    agent_result = {
        "structured_response": None,
        "messages": [
            HumanMessage(content="Question: What is the meal limit?"),
            _ai_message("The meal expense limit while travelling is 60 EUR per day."),
        ],
    }
    answerer = _answerer(monkeypatch, agent_result)

    result = await answerer.answer("What is the meal limit?", CONTEXT)

    assert result.text == "The meal expense limit while travelling is 60 EUR per day."


async def test_agent_computes_cost_from_summed_message_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    decision = AgentAnswer(answer="x", citation_ids=[], confidence="high")
    # DeepAgents can round-trip the model more than once (tool calls); cost should sum both.
    agent_result = {
        "structured_response": decision,
        "messages": [
            _ai_message("", input_tokens=1000, output_tokens=50),
            _ai_message("", input_tokens=200, output_tokens=30),
        ],
    }
    answerer = _answerer(monkeypatch, agent_result, model="claude-haiku-4-5-20251001")

    result = await answerer.answer("q", CONTEXT)

    assert result.usage is not None
    assert result.usage.input_tokens == 1200
    assert result.usage.output_tokens == 80
    # Haiku 4.5: $1/$5 per MTok -> (1200/1e6)*1 + (80/1e6)*5 = 0.0016
    assert result.cost_usd == pytest.approx(0.0016)


async def test_agent_skips_the_llm_call_when_the_preflight_estimate_exceeds_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 100k input tokens on Sonnet 5 ($2/MTok in) alone is $0.20 -- well past the $0.12 answer
    # budget regardless of the output estimate, so the real agent call must never run.
    answerer = _answerer(monkeypatch, None, model="claude-sonnet-5", preflight_input_tokens=100_000)

    def boom(state: object) -> None:
        raise AssertionError("the real agent call must not run when the budget is exceeded")

    monkeypatch.setattr(answerer._agent, "ainvoke", boom)

    result = await answerer.answer("q", CONTEXT)

    assert result.budget_rejected is True
    assert result.cost_usd == 0.0
    assert "couldn't generate a complete answer" in result.text


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


def test_build_system_prompt_adds_a_cache_breakpoint_for_anthropic() -> None:
    settings = Settings(llm_provider="anthropic", anthropic_api_key="sk-ant-fake-test-key")

    result = _build_system_prompt(settings)

    assert isinstance(result, SystemMessage)
    assert result.content == [
        {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
    ]


@pytest.mark.parametrize("provider", ["openai", "ollama"])
def test_build_system_prompt_is_a_plain_string_for_non_anthropic_providers(provider: str) -> None:
    # cache_control is an Anthropic-specific mechanism; OpenAI caches automatically with no API
    # to opt in, and Ollama has no concept of it.
    settings = Settings(llm_provider=provider, openai_api_key="sk-fake-test-key")  # type: ignore[arg-type]

    assert _build_system_prompt(settings) == SYSTEM_PROMPT


def test_build_system_prompt_cache_control_reaches_the_wire_format() -> None:
    """Regression guard for a real bug caught while implementing this: TextContentBlock's typed
    `extras` field looks like the "correct" place for a provider-specific key like cache_control,
    but langchain_anthropic's text-block formatter only reads it from a bare top-level key --
    `extras` is silently dropped for this block type. Assert against the actual formatted output
    langchain_anthropic sends, not just our own message construction."""
    from langchain_anthropic.chat_models import _format_messages

    settings = Settings(llm_provider="anthropic", anthropic_api_key="sk-ant-fake-test-key")
    system_message = _build_system_prompt(settings)
    assert isinstance(system_message, SystemMessage)

    formatted_system, _ = _format_messages([system_message, HumanMessage(content="hi")], model="claude-haiku-4-5")

    assert formatted_system == [
        {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
    ]


def test_factory_falls_back_to_stub_for_openai_without_a_key() -> None:
    without_key = build_pipeline(Settings(llm_provider="openai", openai_api_key=""))
    with_key = build_pipeline(Settings(llm_provider="openai", openai_api_key="sk-fake-test-key"))

    assert type(without_key._answerer).__name__ == "StubAnswerer"
    assert type(with_key._answerer).__name__ == "DeepAgentAnswerer"


def test_factory_uses_real_answerer_for_ollama_with_no_key_needed() -> None:
    pipeline = build_pipeline(Settings(llm_provider="ollama"))
    assert type(pipeline._answerer).__name__ == "DeepAgentAnswerer"


def test_answer_budget_is_consistent_with_the_readme_cost_table() -> None:
    assert ANSWER_BUDGET_USD == pytest.approx(0.12)
