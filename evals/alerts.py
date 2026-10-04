"""Pure evaluation of the alert conditions in README's "Observability and audit trail" ->
"Alert conditions" table, against recent metrics. Separate from evals/check_alerts.py (which
reads live chat_audit_log rows) for the same reason gates.py is separate from
release_gates.py -- the decision logic is what's worth testing in the normal offline suite
(tests/test_alerts.py); gathering the inputs needs a live Postgres.
"""

from dataclasses import dataclass
from enum import StrEnum


class AlertLevel(StrEnum):
    OK = "ok"
    WARN = "warn"
    PAGE = "page"


@dataclass
class AlertMetrics:
    """`None` means "not computable" -- either chat_audit_log's schema doesn't carry what's
    needed (router fallback isn't recorded anywhere yet) or there's no live signal to read
    (judge-flagged hallucination rate needs a scheduled judge run against production traffic,
    which doesn't exist in this project). See evals/check_alerts.py for exactly what each field
    is sourced from."""

    mean_cost_usd_15min: float | None = None
    p95_latency_ms_5min: float | None = None
    error_or_guardrail_rate_10min: float | None = None
    router_fallback_rate_30min: float | None = None
    empty_result_rate_30min: float | None = None
    judge_hallucination_rate_daily: float | None = None
    # These two compare against a 7-day rolling baseline, which needs stored historical
    # aggregates this project doesn't keep anywhere -- always None, never implemented, not just
    # "not computed this run".
    guardrail_trip_rate_vs_baseline: float | None = None
    cache_hit_rate_vs_baseline: float | None = None


@dataclass
class Alert:
    condition: str
    value: float | None
    level: AlertLevel
    detail: str


def _check(
    condition: str,
    value: float | None,
    *,
    warn_at: float | None = None,
    page_at: float | None = None,
    fmt: str = "{:.4f}",
    not_computable_note: str = "not computable with today's chat_audit_log schema",
) -> Alert:
    if value is None:
        return Alert(condition, None, AlertLevel.OK, not_computable_note)
    if page_at is not None and value > page_at:
        detail = f"{fmt.format(value)} exceeds the page threshold {fmt.format(page_at)}"
        return Alert(condition, value, AlertLevel.PAGE, detail)
    if warn_at is not None and value > warn_at:
        detail = f"{fmt.format(value)} exceeds the warn threshold {fmt.format(warn_at)}"
        return Alert(condition, value, AlertLevel.WARN, detail)
    return Alert(condition, value, AlertLevel.OK, f"{fmt.format(value)} within threshold")


def _check_below(
    condition: str,
    value: float | None,
    *,
    warn_below: float,
    fmt: str = "{:.2f}",
    not_computable_note: str,
) -> Alert:
    """Mirror of `_check` for conditions that alert when a value drops *below* a threshold
    (e.g. cache hit rate falling), rather than rising above one."""
    if value is None:
        return Alert(condition, None, AlertLevel.OK, not_computable_note)
    if value < warn_below:
        detail = f"{fmt.format(value)} is below the warn threshold {fmt.format(warn_below)}"
        return Alert(condition, value, AlertLevel.WARN, detail)
    return Alert(condition, value, AlertLevel.OK, f"{fmt.format(value)} within threshold")


def evaluate_alerts(metrics: AlertMetrics) -> list[Alert]:
    return [
        _check(
            "Mean cost/request, 15 min rolling",
            metrics.mean_cost_usd_15min,
            warn_at=0.15,
            page_at=0.30,
            fmt="${:.4f}",
        ),
        _check(
            "P95 latency, 5 min",
            metrics.p95_latency_ms_5min,
            warn_at=6000,
            page_at=15000,
            fmt="{:.0f}ms",
        ),
        _check(
            "5xx / guardrail-block rate, 10 min",
            metrics.error_or_guardrail_rate_10min,
            warn_at=0.02,
            page_at=0.10,
            fmt="{:.1%}",
        ),
        _check(
            "Router fallback rate, 30 min",
            metrics.router_fallback_rate_30min,
            warn_at=0.20,
            fmt="{:.1%}",
            not_computable_note="not computable: the router's own fallback isn't recorded in chat_audit_log today",
        ),
        _check(
            "Empty-result rate (vector or graph), 30 min",
            metrics.empty_result_rate_30min,
            warn_at=0.15,
            fmt="{:.1%}",
        ),
        _check(
            "Judge-flagged hallucination rate, daily",
            metrics.judge_hallucination_rate_daily,
            page_at=0.05,
            fmt="{:.1%}",
            not_computable_note="not computable: no scheduled judge run against production traffic exists",
        ),
        _check(
            "Guardrail trip rate vs. 7-day baseline",
            metrics.guardrail_trip_rate_vs_baseline,
            warn_at=3.0,
            fmt="{:.2f}x",
            not_computable_note="not implemented: needs a stored 7-day rolling baseline this project doesn't keep",
        ),
        _check_below(
            "Prompt cache hit rate vs. 7-day baseline",
            metrics.cache_hit_rate_vs_baseline,
            warn_below=0.5,
            fmt="{:.0%}",
            not_computable_note="not implemented: needs a stored 7-day rolling baseline this project doesn't keep",
        ),
    ]
