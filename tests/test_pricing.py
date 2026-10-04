"""Mini test suite for per-token pricing: cost math, the unknown-model "None, not $0" contract,
and extracting TokenUsage from a langchain AIMessage's usage_metadata.
"""

import pytest
from langchain_core.messages import AIMessage

from src.pipeline.pricing import PARSE_BUDGET_USD, TokenUsage, cost_usd, usage_from_ai_message


def test_cost_usd_matches_the_readme_cost_table_for_a_known_model() -> None:
    # Haiku 4.5: $1/$5 per MTok -> 1000 in + 200 out = 0.001 + 0.001 = 0.002
    usage = TokenUsage(input_tokens=1000, output_tokens=200)
    assert cost_usd("claude-haiku-4-5-20251001", usage) == pytest.approx(0.002)


def test_cost_usd_is_none_for_an_unpriced_model() -> None:
    usage = TokenUsage(input_tokens=1000, output_tokens=200)
    assert cost_usd("some-model-not-in-the-catalog", usage) is None


def test_cost_usd_discounts_cache_reads() -> None:
    full_price = cost_usd("claude-haiku-4-5-20251001", TokenUsage(input_tokens=1000))
    cached = cost_usd("claude-haiku-4-5-20251001", TokenUsage(cache_read_tokens=1000))
    assert full_price is not None and cached is not None
    assert cached == pytest.approx(full_price * 0.1)


def test_usage_from_ai_message_extracts_tokens_and_cache_details() -> None:
    message = AIMessage(
        content="",
        usage_metadata={
            "input_tokens": 300,
            "output_tokens": 40,
            "total_tokens": 340,
            "input_token_details": {"cache_read": 100, "cache_creation": 50},
        },
    )

    usage = usage_from_ai_message(message)

    assert usage.input_tokens == 300
    assert usage.output_tokens == 40
    assert usage.cache_read_tokens == 100
    assert usage.cache_creation_tokens == 50


def test_usage_from_ai_message_defaults_to_zero_without_usage_metadata() -> None:
    usage = usage_from_ai_message(AIMessage(content=""))
    assert usage == TokenUsage()


def test_parse_budget_is_consistent_with_the_readme_cost_table() -> None:
    assert PARSE_BUDGET_USD == pytest.approx(0.01)
