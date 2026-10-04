"""Release-gate thresholds and the pure pass/warn/block decision logic (see README's
"Evaluation and release gates"). Deliberately separate from evals/release_gates.py, which
gathers the live metrics these thresholds are applied to: the decision logic itself has real
behavior worth testing (tests/test_gates.py), and unlike the live script, it needs no API key,
database, or network access to test -- so it runs in the normal, CI-safe offline suite.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class GateStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"


@dataclass
class GateMetrics:
    """Inputs the gates are evaluated against. `None` means "not measured this run" -- a gate
    whose metric is `None` is reported as such, never silently treated as passing."""

    retrieval_hit_rate: float | None = None  # evals/check_retrieval.py, 0-1
    mean_judge_score: float | None = None  # evals/judge.py, 1-5 scale
    min_judge_score: float | None = None  # evals/judge.py, 1-5 scale
    mean_faithfulness_score: float | None = None  # evals/deepeval_suite.py FaithfulnessMetric, 0-1
    latency_p50_ms: float | None = None
    latency_p95_ms: float | None = None
    mean_cost_usd: float | None = None
    # No production traffic exists in this project to sample from -- these stay None always,
    # see README's "Observability and audit trail" for why HITL sampling isn't implemented.
    hitl_acceptable_rate: float | None = None
    hitl_escalation_ratio: float | None = None


@dataclass
class GateResult:
    dimension: str
    metric_name: str
    value: float | None
    status: GateStatus
    detail: str


@dataclass
class GateReport:
    results: list[GateResult]

    @property
    def blocked(self) -> bool:
        return any(r.status is GateStatus.BLOCK for r in self.results)

    @property
    def warned(self) -> bool:
        return any(r.status is GateStatus.WARN for r in self.results)


def _gate(
    dimension: str,
    metric_name: str,
    value: float | None,
    *,
    on_missing: GateStatus,
    blocking: Callable[[float], bool],
    warn: Callable[[float], bool] | None = None,
    fmt: str = "{:.2f}",
) -> GateResult:
    if value is None:
        note = (
            "not applicable (no production traffic)"
            if on_missing is GateStatus.PASS
            else "not measured this run"
        )
        return GateResult(dimension, metric_name, None, on_missing, note)
    if blocking(value):
        detail = f"{fmt.format(value)} breaches the blocking threshold"
        return GateResult(dimension, metric_name, value, GateStatus.BLOCK, detail)
    if warn is not None and warn(value):
        detail = f"{fmt.format(value)} breaches the warn threshold"
        return GateResult(dimension, metric_name, value, GateStatus.WARN, detail)
    return GateResult(dimension, metric_name, value, GateStatus.PASS, f"{fmt.format(value)} within target")


def evaluate_gates(metrics: GateMetrics) -> GateReport:
    results = [
        _gate(
            "Retrieval quality",
            "top-1 hit rate",
            metrics.retrieval_hit_rate,
            on_missing=GateStatus.BLOCK,
            blocking=lambda v: v < 0.90,
            fmt="{:.0%}",
        ),
        _gate(
            "Answer quality (mean)",
            "LLM-judge mean score",
            metrics.mean_judge_score,
            on_missing=GateStatus.BLOCK,
            blocking=lambda v: v < 4.2,
            fmt="{:.2f}/5",
        ),
        _gate(
            "Answer quality (min)",
            "LLM-judge min score",
            metrics.min_judge_score,
            on_missing=GateStatus.BLOCK,
            blocking=lambda v: v < 3,
            fmt="{:.0f}/5",
        ),
        _gate(
            # DeepEval's FaithfulnessMetric is the concrete implementation of both "Citation"
            # rows in the README table (hallucinated claims, uncited claims) -- it scores how
            # well the answer's claims are supported by the retrieved context as one number,
            # rather than the two separate counts the table lists.
            "Citation faithfulness",
            "mean FaithfulnessMetric score",
            metrics.mean_faithfulness_score,
            on_missing=GateStatus.BLOCK,
            blocking=lambda v: v < 0.8,
            fmt="{:.2f}",
        ),
        _gate(
            "Latency",
            "P50 end-to-end",
            metrics.latency_p50_ms,
            on_missing=GateStatus.WARN,
            blocking=lambda v: v > 5000,
            warn=lambda v: v > 2500,
            fmt="{:.0f}ms",
        ),
        _gate(
            "Latency",
            "P95 end-to-end",
            metrics.latency_p95_ms,
            on_missing=GateStatus.WARN,
            blocking=lambda v: v > 10000,
            warn=lambda v: v > 6000,
            fmt="{:.0f}ms",
        ),
        _gate(
            "Cost",
            "mean $/inspection",
            metrics.mean_cost_usd,
            on_missing=GateStatus.WARN,
            blocking=lambda v: v > 0.20,
            warn=lambda v: v > 0.15,
            fmt="${:.4f}",
        ),
        _gate(
            "HITL",
            "sampled acceptable rate",
            metrics.hitl_acceptable_rate,
            on_missing=GateStatus.PASS,
            blocking=lambda v: v < 0.90,
            fmt="{:.0%}",
        ),
        _gate(
            "HITL",
            "escalation rate vs. 7-day baseline",
            metrics.hitl_escalation_ratio,
            on_missing=GateStatus.PASS,
            blocking=lambda v: v > 2.0,
            fmt="{:.2f}x",
        ),
    ]
    return GateReport(results=results)
