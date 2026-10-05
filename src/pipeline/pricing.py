"""Per-token pricing and the per-inspection cost budget (see README's "Cost controls
(tokenomics)"). Deliberately small: only the models this project's router/answerer can actually
select (`src/pipeline/parsing/router.py`'s Anthropic model, and `src/pipeline/models.py`'s
MODEL_CATALOG). Prices are current, best-available list prices per million tokens; Ollama models
are local compute and always $0. An unlisted model returns `None` from `cost_usd` rather than a
guessed price -- callers must treat that as "cost unknown", not "free".
"""

from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage

# One inspection = one /api/chat request/response cycle. Split per stage so no single stage can
# blow the total; see README's "Cost controls (tokenomics)" table for the full rationale.
PARSE_BUDGET_USD = 0.01
ANSWER_BUDGET_USD = 0.12
TOTAL_BUDGET_USD = 0.15

# Job-level limits, one level up from the per-request budget above.
SESSION_DAILY_BUDGET_USD = 1.00  # per session_id, rolling 24h -- see src/api/routes/chat.py
BATCH_JOB_BUDGET_USD = 5.00  # per evals/ script run -- see BatchBudget below


@dataclass(frozen=True)
class ModelPrice:
    input_per_mtok: float
    output_per_mtok: float


PRICING: dict[str, ModelPrice] = {
    # Anthropic
    "claude-sonnet-5": ModelPrice(2.00, 10.00),
    "claude-haiku-4-5-20251001": ModelPrice(1.00, 5.00),
    "claude-opus-5-5": ModelPrice(5.00, 25.00),
    # OpenAI
    "gpt-4.1-nano": ModelPrice(0.10, 0.40),
    "gpt-4o-mini": ModelPrice(0.15, 0.60),
    # Ollama: local compute, no per-token API cost
    "llama3.2:latest": ModelPrice(0.0, 0.0),
    "qwen2.5:14b": ModelPrice(0.0, 0.0),
}


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


def usage_from_ai_message(message: AIMessage) -> TokenUsage:
    """Reads langchain's standardized `usage_metadata` -- every chat model (Anthropic, OpenAI,
    Ollama) populates `input_tokens`/`output_tokens`; `input_token_details.cache_read`/
    `cache_creation` are Anthropic-specific and simply absent (0) for the others."""
    meta: dict[str, Any] = dict(message.usage_metadata or {})
    details: dict[str, Any] = dict(meta.get("input_token_details") or {})
    return TokenUsage(
        input_tokens=meta.get("input_tokens", 0),
        output_tokens=meta.get("output_tokens", 0),
        cache_read_tokens=details.get("cache_read", 0),
        cache_creation_tokens=details.get("cache_creation", 0),
    )


def cost_usd(model: str, usage: TokenUsage) -> float | None:
    """`None` means the model isn't in `PRICING` -- cost is genuinely unknown, not free."""
    price = PRICING.get(model)
    if price is None:
        return None
    # Cache creation is billed like a normal input token (full price); a cache read is
    # Anthropic's documented ~10% of the input rate. Flat 10% is an approximation applied to
    # every provider for simplicity -- fine here since only Anthropic calls populate
    # cache_read_tokens today (see src/pipeline/parsing/router.py).
    billable_input = usage.input_tokens + usage.cache_creation_tokens
    cost = (billable_input / 1_000_000) * price.input_per_mtok
    cost += (usage.cache_read_tokens / 1_000_000) * price.input_per_mtok * 0.1
    cost += (usage.output_tokens / 1_000_000) * price.output_per_mtok
    return round(cost, 6)


class BudgetExceededError(RuntimeError):
    """Raised by BatchBudget.check() once a batch job's cumulative spend crosses its limit --
    a hard circuit breaker: the job stops immediately mid-run rather than degrading silently
    (see README's "Job-level limits")."""


@dataclass
class BatchBudget:
    """Tracks cumulative spend across a batch job (evals/judge.py, evals/deepeval_suite.py,
    evals/release_gates.py) in-process -- unlike the per-request budget, there's no live traffic
    to persist this against, so it only needs to live for the duration of one script run."""

    limit_usd: float = BATCH_JOB_BUDGET_USD
    spent_usd: float = 0.0

    def add(self, cost: float | None) -> None:
        if cost is not None:
            self.spent_usd += cost

    def check(self) -> None:
        if self.spent_usd > self.limit_usd:
            raise BudgetExceededError(
                f"Batch job spend ${self.spent_usd:.4f} exceeded the ${self.limit_usd:.2f} budget "
                f"(BATCH_JOB_BUDGET_USD); stopping mid-run rather than continuing to spend."
            )
